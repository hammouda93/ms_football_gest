import os
import django
from pydub import AudioSegment
from gtts import gTTS
from io import BytesIO
import logging
import speech_recognition as sr

# Set up Django settings before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ms_football_gest.settings')
django.setup()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from gestion_joueurs.models import Player, Video
from .utils import get_players_by_status  # Assuming this function exists to get players by status

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the start command for the bot
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Welcome! Send me a voice message or text with a status like 'pending', 'in_progress', etc.")

# Function to process the voice message
async def process_voice(update: Update, context: CallbackContext):
    try:
        voice = update.message.voice
        file = await voice.get_file()
        audio_file_path = "voice.ogg"
        
        # Download audio file
        await file.download_to_drive(audio_file_path)
        logger.info(f"Downloaded voice message to {audio_file_path}")

        # Convert the OGG file to WAV format using pydub
        wav_file_path = "voice.wav"
        try:
            audio = AudioSegment.from_ogg(audio_file_path)
            audio.export(wav_file_path, format="wav")
            logger.info(f"Converted {audio_file_path} to {wav_file_path}")
        except Exception as e:
            logger.error(f"Error converting audio file: {e}")
            await update.message.reply_text("Error processing the audio file. Please try again.")
            return

        # Convert voice to text using SpeechRecognition
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_file_path) as source:
            audio_data = recognizer.record(source)
            try:
                text = recognizer.recognize_google(audio_data)
                logger.info(f"Recognized text: {text}")
                
                await update.message.reply_text(f"Received status: {text}")
                
                # Process the status
                players = get_players_by_status(text.lower())  # Get players based on the status
                response = "\n".join(players) if players else f"No players found with the status '{text}'."

                # Convert text response to speech
                speech = gTTS(text=response, lang="en")
                bio = BytesIO()
                speech.save(bio)
                bio.seek(0)

                await update.message.reply_voice(voice=bio)
            except sr.UnknownValueError:
                await update.message.reply_text("Sorry, I couldn't understand the voice message. Please try again.")
                logger.error("Google Speech Recognition could not understand the audio.")
            except sr.RequestError as e:
                await update.message.reply_text("Sorry, there was an issue with the speech recognition service. Please try again later.")
                logger.error(f"Google Speech Recognition service error: {e}")
            except Exception as e:
                await update.message.reply_text("An unexpected error occurred while processing the voice message.")
                logger.error(f"Unexpected error: {e}")

    except Exception as e:
        await update.message.reply_text("Sorry, there was an issue with the voice message.")
        logger.error(f"Error handling voice message: {e}")

# Function to handle text status input
async def process_text(update: Update, context: CallbackContext):
    try:
        text = update.message.text.strip().lower()
        logger.info(f"Received text message: {text}")

        # Process the status
        players = get_players_by_status(text)  # Get players based on the status
        response = "\n".join(players) if players else f"No players found with the status '{text}'."

        # Convert text response to speech
        speech = gTTS(text=response, lang="en")
        bio = BytesIO()
        speech.save(bio)
        bio.seek(0)

        await update.message.reply_voice(voice=bio)

    except Exception as e:
        await update.message.reply_text("An unexpected error occurred while processing the text message.")
        logger.error(f"Error handling text message: {e}")

# Set up the Telegram Bot API and application
def main():
    bot_token = "7982870671:AAFqMnSwbUasAaIoVd3gB3ySvMQAZ0mFmh8"  # Replace with your actual bot token

    # Initialize Application
    application = Application.builder().token(bot_token).build()

    # Add command and message handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE, process_voice))  # Handler for voice messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))  # Handler for text messages

    # Start the bot
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()