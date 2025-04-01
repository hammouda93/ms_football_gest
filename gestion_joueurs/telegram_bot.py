import os
import django
from pydub import AudioSegment
from gtts import gTTS
from io import BytesIO
import logging
import speech_recognition as sr
import tempfile
# Set up Django settings before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ms_football_gest.settings')
django.setup()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from gestion_joueurs.models import Player, Video
from gestion_joueurs.utils import get_players_by_status  # Assuming this function exists to get players by status

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the start command for the bot
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Welcome! Send me a voice message or text with a status like 'pending', 'in_progress', etc.")

# Process Voice Message
async def process_voice(update: Update, context: CallbackContext):
    try:
        voice = update.message.voice
        file = await voice.get_file()
        audio_file_path = "voice.ogg"

        # Download audio file
        await file.download_to_drive(audio_file_path)
        logger.info(f"Downloaded voice message: {audio_file_path}")

        # Convert OGG to WAV
        wav_file_path = "voice.wav"
        try:
            audio = AudioSegment.from_ogg(audio_file_path)
            audio.export(wav_file_path, format="wav")
            logger.info(f"Converted OGG to WAV: {wav_file_path}")
        except Exception as e:
            logger.error(f"Audio conversion failed: {e}")
            await update.message.reply_text("Error processing the audio file. Please try again.")
            return

        # Convert Voice to Text
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_file_path) as source:
            audio_data = recognizer.record(source)
            try:
                text = recognizer.recognize_google(audio_data)
                logger.info(f"Recognized text from voice: '{text}'")

                await update.message.reply_text(f"Received status: {text}")

                # Fetch players based on status
                players = get_players_by_status(text.lower())
                response = "\n".join(players) if players else f"No players found with the status '{text}'."

                # Convert Text to Speech
                speech = gTTS(text=response, lang="en")
                bio = BytesIO()
                speech.save(bio)
                bio.seek(0)

                await update.message.reply_voice(voice=bio)
                logger.info("Sent voice response successfully.")

            except sr.UnknownValueError:
                logger.error("Speech Recognition could not understand the audio.")
                await update.message.reply_text("Sorry, I couldn't understand the voice message.")
            except sr.RequestError as e:
                logger.error(f"Speech Recognition service error: {e}")
                await update.message.reply_text("Speech recognition service is unavailable. Try again later.")
            except Exception as e:
                logger.error(f"Unexpected error in voice processing: {e}")
                await update.message.reply_text("An unexpected error occurred while processing the voice message.")

    except Exception as e:
        logger.error(f"Error handling voice message: {e}")
        await update.message.reply_text("There was an issue processing your voice message.")

# Process Text Message
async def process_text(update: Update, context: CallbackContext):
    try:
        text = update.message.text.strip().lower()
        logger.info(f"Received text message: {text}")

        # Fetch players based on status
        players = get_players_by_status(text)
        response = "\n".join(players) if players else f"No players found with the status '{text}'."

        # Convert Text to Speech
        tts = gTTS(text=response, lang="en")

        # Save as MP3
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_mp3:
            tts.save(temp_mp3.name)
            mp3_path = temp_mp3.name

        # Convert MP3 to OGG
        ogg_path = mp3_path.replace(".mp3", ".ogg")
        audio = AudioSegment.from_mp3(mp3_path)
        audio.export(ogg_path, format="ogg")
        logger.info(f"Generated OGG file: {ogg_path}")

        # Send Voice Message
        if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
            with open(ogg_path, "rb") as voice:
                await update.message.reply_voice(voice=voice)
                logger.info(f"Sent voice response successfully: {ogg_path}")
        else:
            logger.error("Error: The generated voice file is empty or missing!")
            await update.message.reply_text("Error generating voice message. Please try again.")

    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        await update.message.reply_text("An unexpected error occurred while processing the text message.")


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