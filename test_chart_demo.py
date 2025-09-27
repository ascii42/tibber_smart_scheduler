#!/usr/bin/env python3
"""Demonstrate the chart functionality for Tibber Smart Scheduler."""

import base64
from datetime import datetime, timedelta

def create_demo_chart():
    """Create a demo chart showing price vs schedule visualization."""

    # Demo data - simulating 24 hours of electricity prices
    prices = []
    labels = []
    current_time = datetime.now().replace(minute=0, second=0, microsecond=0)

    # Generate demo price data (simulating typical daily electricity prices)
    base_prices = [
        0.25, 0.23, 0.21, 0.20, 0.19, 0.18,  # Night hours (cheap)
        0.22, 0.28, 0.35, 0.32, 0.29, 0.26,  # Morning rise
        0.31, 0.33, 0.30, 0.28, 0.27, 0.32,  # Afternoon
        0.38, 0.42, 0.45, 0.41, 0.35, 0.29   # Evening peak
    ]

    for i, base_price in enumerate(base_prices):
        hour_time = current_time + timedelta(hours=i)
        prices.append(base_price)
        labels.append(hour_time.strftime('%H:%M'))

    # Demo schedule window (optimal 2-hour window around 3-5 AM)
    schedule_windows = [{
        'start': '03:00',
        'end': '05:00',
        'avg_price': 0.195,
        'type': 'optimal'
    }]

    # SVG dimensions
    width, height = 600, 300
    margin = 50

    # Calculate scales
    max_price = max(prices)
    min_price = min(prices)
    price_range = max_price - min_price

    # Create SVG
    svg_parts = [
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
        '<style>',
        '.price-line { fill: none; stroke: #2196F3; stroke-width: 3; }',
        '.price-area { fill: rgba(33, 150, 243, 0.1); }',
        '.schedule-bar { fill: rgba(255, 152, 0, 0.4); stroke: #FF9800; stroke-width: 2; }',
        '.axis { stroke: #666; stroke-width: 1; }',
        '.grid { stroke: #eee; stroke-width: 0.5; }',
        '.label { font-family: Arial, sans-serif; font-size: 11px; fill: #333; }',
        '.title { font-family: Arial, sans-serif; font-size: 14px; font-weight: bold; fill: #333; }',
        '.legend { font-family: Arial, sans-serif; font-size: 10px; fill: #666; }',
        '.current-time { stroke: #f44336; stroke-width: 2; stroke-dasharray: 5,5; }',
        '</style>',

        # Title
        f'<text x="{width/2}" y="20" text-anchor="middle" class="title">Tibber Price Chart with Scheduler</text>',

        # Draw grid lines
    ]

    chart_width = width - 2 * margin
    chart_height = height - 2 * margin - 40  # Extra space for title

    # Horizontal grid lines (price levels)
    for i in range(5):
        y = margin + 30 + (i * chart_height / 4)
        price_level = max_price - (i * price_range / 4)
        svg_parts.extend([
            f'<line x1="{margin}" y1="{y}" x2="{width-margin}" y2="{y}" class="grid"/>',
            f'<text x="{margin-5}" y="{y+4}" text-anchor="end" class="label">{price_level:.2f}€</text>'
        ])

    # Vertical grid lines (time)
    for i in range(0, 24, 4):
        x = margin + (i * chart_width / 23)
        svg_parts.extend([
            f'<line x1="{x}" y1="{margin+30}" x2="{x}" y2="{height-margin}" class="grid"/>',
            f'<text x="{x}" y="{height-margin+15}" text-anchor="middle" class="label">{labels[i]}</text>'
        ])

    # Draw axes
    svg_parts.extend([
        f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" class="axis"/>',
        f'<line x1="{margin}" y1="{margin+30}" x2="{margin}" y2="{height-margin}" class="axis"/>',
    ])

    # Draw price area (filled)
    area_points = [f'{margin},{height-margin}']
    line_points = []

    for i, price in enumerate(prices):
        x = margin + (i * chart_width / (len(prices) - 1))
        y = margin + 30 + ((max_price - price) / price_range * chart_height)
        line_points.append(f"{x},{y}")
        area_points.append(f"{x},{y}")

    area_points.append(f'{width-margin},{height-margin}')

    # Draw price area
    svg_parts.append(f'<polygon points="{" ".join(area_points)}" class="price-area"/>')

    # Draw price line
    svg_parts.append(f'<polyline points="{" ".join(line_points)}" class="price-line"/>')

    # Draw schedule windows
    for window in schedule_windows:
        try:
            start_hour = int(window['start'].split(':')[0])
            end_hour = int(window['end'].split(':')[0])

            start_x = margin + (start_hour * chart_width / 23)
            end_x = margin + (end_hour * chart_width / 23)

            # Draw schedule window rectangle
            svg_parts.append(
                f'<rect x="{start_x}" y="{margin+30}" '
                f'width="{end_x - start_x}" height="{chart_height}" '
                f'class="schedule-bar"/>'
            )

            # Add schedule label
            svg_parts.append(
                f'<text x="{(start_x + end_x) / 2}" y="{margin+20}" '
                f'text-anchor="middle" class="legend">Scheduled: {window["start"]}-{window["end"]} '
                f'(Avg: {window["avg_price"]:.3f}€)</text>'
            )
        except Exception:
            continue

    # Draw current time indicator
    current_hour = datetime.now().hour
    current_x = margin + (current_hour * chart_width / 23)
    svg_parts.extend([
        f'<line x1="{current_x}" y1="{margin+30}" x2="{current_x}" y2="{height-margin}" class="current-time"/>',
        f'<text x="{current_x+5}" y="{margin+45}" class="legend">Now</text>'
    ])

    # Add legend
    legend_y = height - 25
    svg_parts.extend([
        f'<line x1="{margin}" y1="{legend_y}" x2="{margin+20}" y2="{legend_y}" class="price-line"/>',
        f'<text x="{margin+25}" y="{legend_y+4}" class="legend">Electricity Price (€/kWh)</text>',

        f'<rect x="{margin+150}" y="{legend_y-5}" width="15" height="10" class="schedule-bar"/>',
        f'<text x="{margin+170}" y="{legend_y+4}" class="legend">Scheduled Window</text>',

        f'<line x1="{margin+280}" y1="{legend_y}" x2="{margin+300}" y2="{legend_y}" class="current-time"/>',
        f'<text x="{margin+305}" y="{legend_y+4}" class="legend">Current Time</text>',
    ])

    svg_parts.append('</svg>')

    # Convert to base64 data URL
    svg_content = ''.join(svg_parts)
    encoded_svg = base64.b64encode(svg_content.encode('utf-8')).decode('utf-8')
    data_url = f"data:image/svg+xml;base64,{encoded_svg}"

    return {
        'svg_content': svg_content,
        'data_url': data_url,
        'demo_data': {
            'prices': prices,
            'labels': labels,
            'schedule_windows': schedule_windows,
            'current_time': datetime.now().strftime('%H:%M')
        }
    }

def save_demo_chart():
    """Save demo chart to file for testing."""
    chart_data = create_demo_chart()

    # Save SVG file
    with open('demo_chart.svg', 'w') as f:
        f.write(chart_data['svg_content'])

    # Save HTML demo
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Tibber Smart Scheduler Chart Demo</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .chart-container {{ text-align: center; margin: 20px 0; }}
        .info {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 10px 0; }}
    </style>
</head>
<body>
    <h1>Tibber Smart Scheduler - Chart Visualization Demo</h1>

    <div class="info">
        <h3>Chart Features:</h3>
        <ul>
            <li><strong>Price Line</strong>: Shows electricity prices over 24 hours</li>
            <li><strong>Scheduled Window</strong>: Orange bars show optimal charging times</li>
            <li><strong>Current Time</strong>: Red dashed line shows current time</li>
            <li><strong>Grid</strong>: Makes it easy to read exact prices and times</li>
        </ul>
    </div>

    <div class="chart-container">
        <h2>Live Chart Preview</h2>
        <img src="{chart_data['data_url']}" alt="Price Chart" style="border: 1px solid #ddd;">
    </div>

    <div class="info">
        <h3>How it works in Home Assistant:</h3>
        <ul>
            <li>Chart data is available as <code>price_chart_url</code> attribute</li>
            <li>Raw data available as <code>price_chart_data</code> attribute</li>
            <li>Schedule windows in <code>schedule_windows</code> attribute</li>
            <li>Can be displayed in dashboard cards or custom Lovelace cards</li>
        </ul>
    </div>

    <div class="info">
        <h3>Usage in Dashboard:</h3>
        <pre><code>type: picture
image: "{{{{ states.switch.tibber_scheduler_dishwasher.attributes.price_chart_url }}}}"
title: "Dishwasher Schedule"</code></pre>
    </div>
</body>
</html>
"""

    with open('demo_chart.html', 'w') as f:
        f.write(html_content)

    print("✅ Demo chart created successfully!")
    print("📁 Files created:")
    print("   - demo_chart.svg (SVG chart)")
    print("   - demo_chart.html (HTML demo page)")
    print("")
    print("🔍 Open demo_chart.html in your browser to see the chart!")

if __name__ == "__main__":
    save_demo_chart()