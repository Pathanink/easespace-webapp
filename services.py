import os
import logging
import json
import torch
import firebase_admin
from firebase_admin import credentials, firestore, auth
import google.generativeai as genai
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = None

try:
    firebase_key_env = os.getenv("FIREBASE_KEY_JSON")
    service_account_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-credentials.json")

    if not firebase_admin._apps:
        cred = None
        
        if firebase_key_env:
            logger.info("🌍 Found FIREBASE_KEY_JSON. Loading from variable...")
            cred_dict = json.loads(firebase_key_env)
            cred = credentials.Certificate(cred_dict)
            
        elif os.path.exists(service_account_path):
            logger.info(f"💻 Found local key file: {service_account_path}")
            cred = credentials.Certificate(service_account_path)
            
        else:
            logger.warning("❌ No Firebase credentials found! (Check .env or json file)")

        if cred:
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            logger.info("✅ Firebase connected successfully.")
    else:
        db = firestore.client()
        logger.info("✅ Firebase already initialized.")

except Exception as e:
    logger.error(f"❌ Firebase initialization error: {e}")


gemini_model = None
gemini_enabled = False

try:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        
        generation_config = {
            "temperature": 0.7,
            "top_p": 1,
            "top_k": 1,
            "max_output_tokens": 2048,
        }
        
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        
        gemini_model = genai.GenerativeModel(
            model_name="gemini-2.5-flash-lite", 
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        gemini_enabled = True
        logger.info("✅ Gemini AI initialized successfully.")
    else:
        logger.warning("⚠️ GEMINI_API_KEY not found.")
except Exception as e:
    logger.error(f"❌ Gemini AI initialization error: {e}")


tokenizer = None
model = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

try:
    model_dir = os.getenv("MODEL_DIR", "final_model") 
    
    if os.path.exists(model_dir):
        logger.info(f"📂 Found model directory: {model_dir}. Loading WangchanBERTa...")
        
        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        
        model.to(device)
        model.eval()
        
        logger.info(f"✅ WangchanBERTa loaded successfully on {device}.")
    else:
        logger.warning(f"⚠️ Model directory '{model_dir}' not found. Local AI will be disabled.")
        
except Exception as e:
    logger.error(f"❌ Model loading error: {e}")