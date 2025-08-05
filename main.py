import os
import requests
from typing import Type
from datetime import datetime, timedelta, UTC
from textwrap import dedent
import json
import pandas as pd
from langchain_community.chat_models import ChatOllama
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tools.Weather_tools import GetCoordinatesTool, GetOpenMeteoWeatherTool


os.environ["OPENAI_API_KEY"] = "insert-api-key"


# Load the API key from the .env file
load_dotenv()
openai_api_key = os.environ.get("insert-api-key")
# WARNING: Do not commit your API key to version control!
from langchain_openai import ChatOpenAI

# Replace 'YOUR_API_KEY_HERE' with your actual key
ollama_llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,
    api_key=openai_api_key
)



# --- Instantiate the tools ---
get_coordinates_tool = GetCoordinatesTool()
get_open_meteo_weather_tool = GetOpenMeteoWeatherTool()

# --- Agent Definitions ---
geocoding_specialist = Agent(
    role='Geocoding Specialist',
    goal=dedent("Accurately convert location names into geographical coordinates."),
    backstory=dedent("You are an expert in geographical information systems."),
    tools=[get_coordinates_tool],
    verbose=False,
    allow_delegation=False,
    llm=ollama_llm
)

#This agent will now handle both fetching and analyzing the data
weather_data_analyst = Agent(
    role='Weather Data Analyst',
    goal=dedent("First, retrieve a JSON weather report for a location and then, analyze it to provide a simple English summary with recommendations."),
    backstory=dedent("You are a highly skilled weather analyst who is also an expert at using tools to fetch raw, structured data. You are excellent at translating complex data into actionable, easy-to-understand advice for families."),
    tools=[get_open_meteo_weather_tool], # The tool is assigned to the agent
    verbose=False,
    allow_delegation=False,
    llm=ollama_llm
)
# --- Task Definitions ---
get_coordinates_task = Task(
    description=dedent("Find the latitude and longitude for the location: '{location}'."),
    expected_output="A single plain string of 'latitude,longitude'.",
    agent=geocoding_specialist,
)


# --- Updated and More Detailed Analyze Weather Task ---
analyze_weather_task = Task(
    description=dedent("""
        Analyze the detailed JSON weather report you have received from the previous task.
        Your final output must be a single, friendly, natural-language paragraph. Follow these steps:

        1.  **Start with the "Right Now" Summary:**
            - State the current temperature, rain status, and wind speed.
            - Provide a quick assessment of the current air quality based on the `pm10` and `pm2_5` values. Use simple terms like "good," "moderate," or "poor."
            - Example phrase: "The current temperature is 15°C with light winds and good air quality."

        2.  **Provide a "Future Outlook" (Next 2-3 hours):**
            - Look at the `plus_1_hour` and `plus_2_hour` forecast for any changes in temperature, rain, or wind.
            - Mention if conditions are expected to improve, worsen, or stay the same.
            - Based on the `river_discharge` data, briefly mention any flood risk for the coming days. Use a simple statement like "The risk of river flooding is low."

        3.  **Give Clear Activity Recommendations:**
            - Based on your full analysis, provide specific advice for two activities:
                - **Walking:** Recommend a walk only if there is little to no rain, wind is calm, and air quality is good (PM levels are low).
                - **Swimming Pool:** Recommend visiting a swimming pool if the temperature is comfortable (e.g., above 20°C) and there is no rain.
            - **PRIORITIZE SAFETY:** If conditions are poor (high wind, heavy rain, poor air quality, or high flood risk), your main recommendation should be to stay indoors and be cautious.

        Your final output must be a seamless, single paragraph that combines these three points into a helpful report for a human. Do not list the points, just write a well-structured paragraph.
    """),
    expected_output="A natural-language paragraph summarizing the current and future weather conditions with clear, safe recommendations for walking or swimming.",
    agent=weather_data_analyst,
    context=[get_coordinates_task]
)
# --- 5. Crew Definition and Execution ---
if __name__ == "__main__":
    print("## Weather Forecasting Crew ##")
    print("-------------------------------")

    # Get location from command line, default to Austin, Texas, USA
    if len(sys.argv) > 1:
        input_location = sys.argv[1]
    else:
        input_location = "Austin, Texas, USA"
        print("No location provided. Defaulting to 'Austin, Texas, USA'.")

    crew = Crew(
        agents=[geocoding_specialist, weather_data_analyst],
        tasks=[get_coordinates_task, analyze_weather_task],
        verbose=False, # turn on if needed details
        process=Process.sequential
    )

    # --- Execute Crew ---
    result = crew.kickoff(inputs={"location": input_location})

    print("\n\n################################################")
    print("## Here is the Weather Agent's final result:")
    print("################################################\n")
    print(result)
