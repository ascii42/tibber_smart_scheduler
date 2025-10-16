"""Tibber API client for fetching price data."""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import asyncio

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

_LOGGER = logging.getLogger(__name__)

TIBBER_API_URL = "https://api.tibber.com/v1-beta/gql"


class TibberApiClient:
    """Client for Tibber GraphQL API."""

    def __init__(self, access_token: str, session: Optional[Any] = None):
        """Initialize the Tibber API client."""
        self._access_token = access_token
        self._session: Optional[Any] = session
        self._own_session = False
        self._homes: List[Dict[str, Any]] = []

    async def _get_session(self) -> Any:
        """Get or create aiohttp session."""
        if self._session is None:
            if not AIOHTTP_AVAILABLE:
                raise ImportError("aiohttp is required for API access")
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self):
        """Close the session if we own it."""
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def _query(self, query: str) -> Optional[Dict]:
        """Execute GraphQL query."""
        try:
            session = await self._get_session()
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }

            timeout = aiohttp.ClientTimeout(total=30) if AIOHTTP_AVAILABLE else 30

            async with session.post(
                TIBBER_API_URL,
                json={"query": query},
                headers=headers,
                timeout=timeout,
            ) as response:
                if response.status != 200:
                    _LOGGER.error(f"Tibber API returned status {response.status}")
                    return None

                data = await response.json()

                if "errors" in data:
                    _LOGGER.error(f"Tibber API errors: {data['errors']}")
                    return None

                return data.get("data")

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout connecting to Tibber API")
            return None
        except Exception as e:
            _LOGGER.error(f"Error querying Tibber API: {e}")
            return None

    async def get_homes(self) -> List[Dict[str, Any]]:
        """Get list of homes from Tibber account."""
        query = """
        {
          viewer {
            homes {
              id
              appNickname
              address {
                address1
                postalCode
                city
              }
              features {
                realTimeConsumptionEnabled
              }
            }
          }
        }
        """

        try:
            data = await self._query(query)
            if data and "viewer" in data and "homes" in data["viewer"]:
                self._homes = data["viewer"]["homes"]
                _LOGGER.info(f"Found {len(self._homes)} Tibber homes")
                return self._homes
            return []

        except Exception as e:
            _LOGGER.error(f"Error fetching homes: {e}")
            return []

    async def get_price_info(self, home_id: Optional[str] = None) -> Optional[Dict]:
        """Get price information for a home with detailed breakdown."""
        query = """
        {
          viewer {
            homes {
              id
              currentSubscription {
                priceInfo {
                  current {
                    total
                    energy
                    tax
                    startsAt
                    currency
                    level
                  }
                  today {
                    total
                    energy
                    tax
                    startsAt
                    currency
                    level
                  }
                  tomorrow {
                    total
                    energy
                    tax
                    startsAt
                    currency
                    level
                  }
                }
              }
            }
          }
        }
        """

        try:
            data = await self._query(query)
            if not data or "viewer" not in data:
                return None

            homes = data["viewer"].get("homes", [])
            if not homes:
                _LOGGER.warning("No homes found in Tibber account")
                return None

            # If specific home_id provided, find it
            if home_id:
                home = next((h for h in homes if h["id"] == home_id), None)
                if not home:
                    _LOGGER.error(f"Home {home_id} not found")
                    return None
            else:
                # Use first home
                home = homes[0]
                _LOGGER.info(f"Using first home: {home.get('id')}")

            subscription = home.get("currentSubscription")
            if not subscription:
                _LOGGER.error("No subscription found for home")
                return None

            price_info = subscription.get("priceInfo")
            if not price_info:
                _LOGGER.error("No price info found")
                return None

            # Log what we got
            today_count = len(price_info.get("today", []))
            tomorrow_count = len(price_info.get("tomorrow", []))
            _LOGGER.info(
                f"Fetched price data: {today_count} today prices, "
                f"{tomorrow_count} tomorrow prices"
            )

            return price_info

        except Exception as e:
            _LOGGER.error(f"Error fetching price info: {e}")
            return None

    def format_price_data(self, price_info: Dict) -> Dict[str, Any]:
        """Format price info with detailed breakdown."""
        try:
            today = price_info.get("today", [])
            tomorrow = price_info.get("tomorrow", [])
            current = price_info.get("current", {})

            # Format to match expected structure with full details
            formatted_today = [
                {
                    "starts_at": p["startsAt"],
                    "total": p["total"],
                    "energy": p.get("energy"),
                    "tax": p.get("tax"),
                    "currency": p.get("currency", "EUR"),
                    "level": p.get("level", "NORMAL"),
                }
                for p in today
            ]

            formatted_tomorrow = [
                {
                    "starts_at": p["startsAt"],
                    "total": p["total"],
                    "energy": p.get("energy"),
                    "tax": p.get("tax"),
                    "currency": p.get("currency", "EUR"),
                    "level": p.get("level", "NORMAL"),
                }
                for p in tomorrow
            ]

            return {
                "today": formatted_today,
                "tomorrow": formatted_tomorrow,
                "current": {
                    "total": current.get("total"),
                    "energy": current.get("energy"),
                    "tax": current.get("tax"),
                    "currency": current.get("currency", "EUR"),
                    "level": current.get("level", "NORMAL"),
                    "starts_at": current.get("startsAt"),
                } if current else None,
            }

        except Exception as e:
            _LOGGER.error(f"Error formatting price data: {e}")
            return {"today": [], "tomorrow": [], "current": None}


async def test_api_connection(access_token: str) -> bool:
    """Test Tibber API connection."""
    client = TibberApiClient(access_token)
    try:
        homes = await client.get_homes()
        if homes:
            _LOGGER.info(f"Successfully connected to Tibber API. Found {len(homes)} homes")
            for home in homes:
                _LOGGER.info(
                    f"  - {home.get('appNickname', 'Unknown')} "
                    f"({home.get('address', {}).get('postalCode', 'N/A')})"
                )
            return True
        return False
    finally:
        await client.close()
