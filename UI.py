import json
from flask import Flask, render_template

app = Flask(__name__)

# Sample JSON data including the summary

with open('weather_forecast.json', 'r') as f:
	WEATHER_DATA_JSON = json.load(f)
@app.route('/')
def index():
    return render_template('index.html', weather_data=WEATHER_DATA_JSON)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
