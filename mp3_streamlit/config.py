import os
import sqlite3
import json
import time
import textwrap
import requests
import pandas as pd
import yfinance as yf
import streamlit as st 

from dataclasses import dataclass, field
from openai import OpenAI

AV_BASE = "https://www.alphavantage.co"

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
ALPHAVANTAGE_API_KEY = st.secrets["ALPHAVANTAGE_API_KEY"]

client = OpenAI(api_key=OPENAI_API_KEY)

ACTIVE_MODEL = "gpt-4o-mini"