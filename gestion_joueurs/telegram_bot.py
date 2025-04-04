import os
import django
from pydub import AudioSegment
from gtts import gTTS
import logging
import speech_recognition as sr
import tempfile
from telegram import InlineKeyboardButton, InlineKeyboardMarkup,KeyboardButton
from telegram.ext import MessageHandler, CallbackQueryHandler, filters
#from text_to_num import text2num
#from word2number_fr import w2n


# Set up Django settings before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ms_football_gest.settings')
django.setup()

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from gestion_joueurs.utils import get_players_by_status, get_payment_details,search_players,process_payment
from gestion_joueurs.utils import get_videos_by_deadline,get_players_by_invoice_status

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Start Command - Shows options
async def start(update: Update, context: CallbackContext):
    """Send a welcome message with two choices."""
    keyboard = [["Video Status"], ["Payment Status"], ["Player Invoice"], ["Workflow"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "Welcome! Please choose an option:\n\n"
        "🎥 *Video Status*: Check the status of players' videos.\n"
        "💰 *Payment Status*: Check payment status (Paid, Unpaid, Partially Paid).\n"
        "➕💰 *Player Invoice*: Check a player's payment details (eg: richard facture).\n"
        "📋 *Workflow*: Check what do you have on the list.\n\n"
        "Simply type or send a voice message with your choice!",
        reply_markup=reply_markup,
    )

# Function to generate and send voice response
async def send_voice_response(update: Update, response: str):
    """Generate TTS response and send as voice message."""
    try:
        if not response.strip():
            logger.error("Error: Empty response text!")
            await update.message.reply_text("Error generating voice message. Please try again.")
            return
        
        # Generate speech from text
        tts = gTTS(text=response, lang="en")

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_mp3:
            tts.save(temp_mp3.name)
            mp3_path = temp_mp3.name

        # Convert MP3 to OGG
        ogg_path = mp3_path.replace(".mp3", ".ogg")
        audio = AudioSegment.from_mp3(mp3_path)
        audio.export(ogg_path, format="ogg")

        # Send voice response
        if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
            with open(ogg_path, "rb") as voice:
                await update.message.reply_voice(voice=voice)
                logger.info(f"Sent voice response successfully: {ogg_path}")
        else:
            logger.error("Error: Generated voice file is empty!")
            await update.message.reply_text("Error generating voice message. Please try again.")
    
    except Exception as e:
        logger.error(f"Unexpected error in voice processing: {e}")
        await update.message.reply_text("An unexpected error occurred while processing the voice message.")

# Process Text and Voice Messages
async def process_request(text: str) -> str:
    """Handles both video status and payment status requests based on input."""
    try:
        text = text.strip().lower()
        logger.info(f"Processing request: {text}")

        if text == "video status":
            return "Please type a video status (e.g., 'pending', 'completed')."

        if text == "Player Invoice":
            return "Please type the player's name followed by 'facture' (e.g., 'Richard facture')."
        
        if text == "workflow":
            return "Please type 'workflow' and choose the deadline you want (e.g., 'Today')."
        
        if text == "Payment Status":
            return "Please type a video status (Paid, Unpaid, Partially Paid)."
        
        response = ""
        if "facture" in text:
            player_name = text.replace("facture", "").strip()
            logger.info(f"Fetching payment details for player: {player_name}")
            response = await get_payment_details(player_name)

        return response if response else "No relevant data found."

    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return "An unexpected error occurred while processing the request."

# Store ongoing player selections
pending_player_selections = {}
async def handle_request(text: str, update: Update, context: CallbackContext):
    """Handles both text and voice inputs by processing requests."""
    user_id = update.message.from_user.id

    # Handle player selection first
    if user_id in pending_player_selections:
        selected_player = text
        del pending_player_selections[user_id]  
        response, player_id, video_status = await get_payment_details(selected_player)
        context.user_data["selected_player"] = selected_player
        context.user_data["selected_player_id"] = player_id
        logger.info(f"Stored selected_player_id: {player_id} for user {user_id}")

        keyboard = [["Paiement"], ["Changer le status"], ["Menu"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

        await update.message.reply_text(response)
        await update.message.reply_text("Choisissez une option :", reply_markup=reply_markup)
        await send_voice_response(update, response)
        return  # Exit here so it doesn't process further commands
    
    # ✅ Check for payment input if awaiting payment
    if context.user_data.get("awaiting_confirmation"):
        await handle_payment_confirmation(update, context)
        return
    
    if "awaiting_payment" in context.user_data:
        # Call handle_payment_input for payment amount entry
        await handle_payment_input(update, context)
        return
    
    
    
    # ✅ Now check "Paiement" after a player is already selected
    if text.lower() == "paiement":
        player_id = context.user_data.get("selected_player_id")  # Get stored player_id
        if player_id:
            context.user_data["awaiting_payment"] = player_id
            logger.info(f"User {user_id} selected 'Paiement' for player ID: {player_id}. Awaiting payment input.")
            await update.message.reply_text("Envoyez un montant (voix ou texte) pour le paiement.")
        else:
            logger.error(f"User {user_id} attempted 'Paiement' but no selected player ID found.")
            await update.message.reply_text("Erreur : Aucun joueur sélectionné. Veuillez d'abord rechercher un joueur.")
        return

    if text == "menu":
        # Reset user data context
        context.user_data.clear()
        await start(update, context)
        return
    
    if text == "player invoice":
        await update.message.reply_text("Please type the player's name followed by 'facture' (e.g., 'Richard facture').")
        return

    if text == "payment status":
        keyboard = [["Paid"], ["Unpaid"], ["Partially Paid"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text("Select a payment status:", reply_markup=reply_markup)
        return

    # Map user selection to invoice statuses
    invoice_status_mapping = {
        "paid": "paid",
        "unpaid": "unpaid",
        "partially paid": "partially_paid"
    }

    if text in invoice_status_mapping:
        status = invoice_status_mapping[text]
        players = await get_players_by_invoice_status(status)
        response = "\n".join(players) if players else f"No players found with status '{text}'."
        await update.message.reply_text(response)
        await send_voice_response(update, response)
        return
    
    if text == "video status":
        keyboard = [
            ["Pending"], ["In Progress"], ["Completed Collab"],
            ["Completed"], ["Delivered"], ["Problematic"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text("Select a video status:", reply_markup=reply_markup)
        return

    status_mapping = {
        "pending": "pending",
        "in progress": "in_progress",
        "completed collab": "completed_collab",
        "completed": "completed",
        "delivered": "delivered",
        "problematic": "problematic"
    }

    if text in status_mapping:
        status = status_mapping[text]
        players = await get_players_by_status(status)
        response = "\n".join(players) if players else f"No players found for status '{text}'."
        await update.message.reply_text(response)
        await send_voice_response(update, response)
        return

    if text == "workflow":
        keyboard = [["A week ago"], ["Today"], ["In three days"], ["In a week"], ["In two weeks"], ["In a month"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text("Select a deadline period:", reply_markup=reply_markup)
        return

    deadline_mapping = {
        "a week ago": "past",
        "today": "today",
        "in three days": "3_days",
        "in a week": "1_week",
        "in two weeks": "2_weeks",
        "in a month": "1_month"
    }

    if text in deadline_mapping:
        deadline_filter = deadline_mapping[text]
        videos = await get_videos_by_deadline(deadline_filter)
        response = "\n".join(videos)
        await update.message.reply_text(response)
        await send_voice_response(update, response)
        return

        # Invoice Request
    if "facture" in text:
        player_name = text.replace("facture", "").strip()
        possible_players = await search_players(player_name)

        if not possible_players:
            await update.message.reply_text(f"No players found with the name '{player_name}'. Try again.")
            return

        if len(possible_players) == 1:
            response, player_id, video_status,player = await get_payment_details(possible_players[0])

            if not player_id:
                await update.message.reply_text("❌ Player not found or has no invoice.")
                return

            # Store selected player ID
            context.user_data["selected_player"] = player
            context.user_data["selected_player_id"] = player_id
            logger.info(f"Stored selected_player_id: {player_id} for user {user_id}")

            # Display payment options
            keyboard = [["Paiement"], ["Changer le status"], ["Menu"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text(response)
            await update.message.reply_text("Choisissez une option :", reply_markup=reply_markup)

        else:
            pending_player_selections[user_id] = possible_players
            keyboard = [[name] for name in possible_players]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text("Multiple players found. Please select one:", reply_markup=reply_markup)

        return
    
    
    response = await process_request(text)
    await update.message.reply_text(response)
    await send_voice_response(update, response)

async def handle_payment_input(update: Update, context: CallbackContext):
    """Handle payment amount and payment method input."""
    if "awaiting_payment" in context.user_data:
        player_id = context.user_data["awaiting_payment"]
        player = context.user_data["selected_player"]
        message = update.message.text if update.message.text else ""

        try:
            # Extract the amount (assuming it's the first number in the message)
            amount = float(message.split()[0])  # Extract the first number as amount
            context.user_data["payment_amount"] = amount  # Store amount for confirmation

            # Extract payment method
            payment_method = "bank_transfer"  # Default method if no specific payment method found
            if "cash" in message.lower():
                payment_method = "cash"
            elif "poste" in message.lower():
                payment_method = "la_poste"

            context.user_data["payment_method"] = payment_method  # Store payment method for confirmation

            # Log the amount and payment method
            logger.info(f"User {update.message.from_user.id} entered payment amount: {amount} and payment method: {payment_method} for player ID: {player_id}")

            # Prepare the message
            payment_method_name = "Cash" if payment_method == "cash" else "La Poste" if payment_method == "la_poste" else "Bank Transfer"
            await update.message.reply_text(f"{player} ({player_id}) a payé {amount} TND par {payment_method_name}. Confirmer?")

            # Display confirmation buttons
            keyboard = [
                [KeyboardButton("Oui")],
                [KeyboardButton("Non")]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            context.user_data["awaiting_confirmation"] = True  # 👈 Add this
            await update.message.reply_text("Confirmez la transaction :", reply_markup=reply_markup)
            return
        except ValueError:
            logger.warning(f"User {update.message.from_user.id} entered an invalid amount: {message}")
            context.user_data.clear()
            await start(update, context)

async def handle_payment_confirmation(update: Update, context: CallbackContext):
    """Handle the user's response to confirm or cancel the payment."""
    message = update.message.text.strip().lower()

    # Check if the user response is 'oui' or 'non' before proceeding
    if message in ["oui", "non"]:
        if message == "oui":
            # Check if payment details are available in context
            if "awaiting_payment" in context.user_data and "payment_amount" in context.user_data and "payment_method" in context.user_data:
                player_id = context.user_data["awaiting_payment"]
                amount = context.user_data["payment_amount"]
                payment_method = context.user_data["payment_method"]

                # Process the payment
                success = await process_payment(player_id, amount, payment_method)
                if success:
                    await update.message.reply_text("✅ Paiement enregistré avec succès !")
                    context.user_data.pop("awaiting_confirmation", None)
                    context.user_data.pop("awaiting_payment", None)
                    context.user_data.pop("payment_amount", None)
                    context.user_data.pop("payment_method", None)
                else:
                    await update.message.reply_text("❌ Erreur lors de l’enregistrement du paiement.")
                
                # Clean up context data after payment processing
                context.user_data.pop("awaiting_payment", None)
                context.user_data.pop("payment_amount", None)
                context.user_data.pop("payment_method", None)

        elif message == "non":
            # Clear user data and cancel the transaction
            context.user_data.clear()
            await update.message.reply_text("❌ Transaction annulée.")
            await start(update, context)

    else:
        # Prompt the user to respond with 'oui' or 'non' if the input is invalid
        await update.message.reply_text("❌ Veuillez répondre par 'Oui' ou 'Non'.")





async def process_text(update: Update, context: CallbackContext):
    """Handle text messages."""
    text = update.message.text.strip().lower()
    await handle_request(text, update, context)

async def process_voice(update: Update, context: CallbackContext):
    """Handle voice messages by converting speech to text and processing."""
    try:
        logger.info("Received a voice message.")
        voice = update.message.voice
        file = await voice.get_file()
        audio_file_path = "voice.ogg"

        # Download and convert audio
        await file.download_to_drive(audio_file_path)
        logger.info(f"Downloaded voice message: {audio_file_path}")

        wav_file_path = "voice.wav"
        audio = AudioSegment.from_ogg(audio_file_path)
        audio.export(wav_file_path, format="wav")

        # Recognize speech
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_file_path) as source:
            audio_data = recognizer.record(source)
            if not audio_data:
                logger.error("Empty audio data received.")
                await update.message.reply_text("Désolé, je n'ai pas compris le message vocal.")
                return

            try:
                # Try English first
                text = recognizer.recognize_google(audio_data, language="en-US").lower().strip()

                # Try French if invoice/payment words detected
                fr_text = recognizer.recognize_google(audio_data, language="fr-FR").lower().strip()

                if fr_text:
                    logger.info(f"French detected: {fr_text}")
                else:
                    logger.warning("French recognition returned empty text.")

                if any(keyword in fr_text for keyword in ["facture", "dinar", "dinars", "cash", "poste", "virement"]):
                    text = fr_text
                    logger.info(f"Detected French input: {text}")

            except sr.UnknownValueError:
                logger.error("Could not recognize speech in either language.")
                await update.message.reply_text("Désolé, je n'ai pas compris le message vocal.")
                return
            except sr.RequestError as e:
                logger.error(f"Speech Recognition service error: {e}")
                await update.message.reply_text("Speech recognition service is unavailable. Try again later.")
                return

        # Debugging: Log the final text before passing it
        logger.info(f"Final processed text: {text}")

        # Pass processed text to handle_request
        await handle_request(text, update, context)

    except Exception as e:
        logger.error(f"Unexpected error in voice processing: {e}")
        await update.message.reply_text("An unexpected error occurred while processing the voice message.")




# Set up the Telegram Bot API and application
def main():
    bot_token = "7982870671:AAFqMnSwbUasAaIoVd3gB3ySvMQAZ0mFmh8"  # Replace with your actual bot token

    # Initialize Application
    application = Application.builder().token(bot_token).build()

    # Add command and message handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))  # Handles text messages
    application.add_handler(MessageHandler(filters.VOICE, process_voice))  # Handles voice messages

    # Start the bot
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()