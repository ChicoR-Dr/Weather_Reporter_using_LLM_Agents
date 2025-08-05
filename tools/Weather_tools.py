import os
import requests
from typing import Type
from datetime import datetime, timedelta, UTC
from textwrap import dedent

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool
from dotenv import load_dotenv
from pydantic import BaseModel, Field

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry
from datetime import datetime
import json



# Copy your tool classes here, exactly as they are in your main script
# --- Define a Pydantic Model for tool inputs ---
class GetCoordinatesInput(BaseModel):
    location: str = Field(
        description="The geographical location (e.g., city, country) to get coordinates for."
    )

# --- Define the custom tools ---
class GetCoordinatesTool(BaseTool):
    name: str = "Get Coordinates"
    description: str = "Useful for fetching the latitude and longitude for a given location using Nominatim. The input MUST be a single plain string for the 'location' argument, for example: 'Paris'."
    args_schema: Type[BaseModel] = GetCoordinatesInput

    def _run(self, location: str) -> str:
        base_url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": location,
            "format": "json",
            "limit": 1
        }
        headers = {
            "User-Agent": "CrewAI Weather Agent (your-email@example.com)"
        }
        try:
            response = requests.get(base_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                return f"{lat},{lon}"
            else:
                return f"Error: Could not find coordinates for {location}."
        except requests.exceptions.RequestException as e:
            return f"Error fetching coordinates: {e}"




class GetOpenMeteoWeatherInput(BaseModel):
    coordinates: str = Field(description="The latitude and longitude in 'latitude,longitude' format.")

class GetOpenMeteoWeatherTool(BaseTool):
    name: str = "Get Open-Meteo Weather"
    description: str = (
        "**IMPORTANT: The EXACT name of this tool is 'Get Open-Meteo Weather'. Do NOT modify it.** "
        "Fetches current weather, air quality, flood risk, and historical rainfall using coordinates in 'latitude,longitude' format. "
        "Returns a combined summary and activity recommendation."
    )
    args_schema: Type[BaseModel] = GetOpenMeteoWeatherInput

    def _run(self, coordinates: str) -> str:
        try:
            lat, lon = map(float, coordinates.split(','))
        except ValueError:
            return "❌ Error: Invalid coordinate format. Use 'latitude,longitude'."

        summary = [f"📍 Weather Report for {lat:.4f}, {lon:.4f}\n"]
        print(f"📍 Generating Weather Report for {lat:.4f}, {lon:.4f}\n")
        # ------------------------ Setup ------------------------
        cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
        retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
        openmeteo = openmeteo_requests.Client(session=retry_session)
        
        now_utc = pd.Timestamp.utcnow().replace(minute=0, second=0, microsecond=0)
        plus_1h = now_utc + pd.Timedelta(hours=1)
        plus_2h = now_utc + pd.Timedelta(hours=2)
        today_date = now_utc.normalize()
        tomorrow_date = today_date + pd.Timedelta(days=1)
        day_after_date = today_date + pd.Timedelta(days=2)
        
        # ------------------------ WEATHER ------------------------
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ["rain", "temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
        }
        weather_response = openmeteo.weather_api(weather_url, params=weather_params)[0]
        hourly = weather_response.Hourly()
        weather_df = pd.DataFrame({
            "datetime": pd.date_range(
                start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
                end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=hourly.Interval()),
                inclusive="left"
            ),
            "rain": hourly.Variables(0).ValuesAsNumpy(),
            "temperature": hourly.Variables(1).ValuesAsNumpy(),
            "humidity": hourly.Variables(2).ValuesAsNumpy(),
            "wind_speed": hourly.Variables(3).ValuesAsNumpy()
        }).set_index("datetime")
        
        # ------------------------ AIR QUALITY ------------------------
        air_url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        air_params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ["pm10", "pm2_5"],
        }
        air_response = openmeteo.weather_api(air_url, params=air_params)[0]
        hourly = air_response.Hourly()
        air_df = pd.DataFrame({
            "datetime": pd.date_range(
                start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
                end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=hourly.Interval()),
                inclusive="left"
            ),
            "pm10": hourly.Variables(0).ValuesAsNumpy(),
            "pm2_5": hourly.Variables(1).ValuesAsNumpy()
        }).set_index("datetime")
        
        # ------------------------ FLOOD ------------------------
        flood_url = "https://flood-api.open-meteo.com/v1/flood"
        flood_params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge",
        }
        flood_response = openmeteo.weather_api(flood_url, params=flood_params)[0]
        daily = flood_response.Daily()
        flood_df = pd.DataFrame({
            "date": pd.date_range(
                start=pd.to_datetime(daily.Time(), unit="s", utc=True),
                end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=daily.Interval()),
                inclusive="left"
            ),
            "river_discharge": daily.Variables(0).ValuesAsNumpy()
        }).set_index("date")
        
        def get_daily_value_safe(df, date_key):
            try:
                return df.loc[date_key].item()
            except KeyError:
                return None
        
        
        
        
        # ------------------------ Assemble JSON ------------------------
        
        def get_row_nearest(df, target_time):
            try:
                return df.loc[target_time].to_dict()
            except KeyError:
                return df[df.index >= target_time].iloc[0].to_dict()
        
        forecast_json = {
            "current": get_row_nearest(weather_df, now_utc),
            "plus_1_hour": get_row_nearest(weather_df, plus_1h),
            "plus_2_hour": get_row_nearest(weather_df, plus_2h),
        }
        
        air_quality_json = {
            "current": get_row_nearest(air_df, now_utc),
            "plus_1_hour": get_row_nearest(air_df, plus_1h),
            "plus_2_hour": get_row_nearest(air_df, plus_2h),
        }
        
        river_discharge_json = {
            "today": get_daily_value_safe(flood_df, today_date),
            "tomorrow": get_daily_value_safe(flood_df, tomorrow_date),
            "day_after_tomorrow": get_daily_value_safe(flood_df, day_after_date),
        }
        loc = {
            "latitude":lat,
            "longitude":lon
        }
        
        weather_json = {
            "location": loc,
            "forecast": forecast_json,
            "air_quality": air_quality_json,
            "river_discharge": river_discharge_json
        }
        
        # ------------------------ Print ------------------------
        with open("weather_forecast.json", "w") as f:
            json.dump(weather_json, f, indent=4)
        #print(json.dumps(weather_json, indent=4, default=str))

        return weather_json