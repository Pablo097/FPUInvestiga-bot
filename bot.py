from google.oauth2 import service_account
import gspread, json, os, re

import logging
from typing import Optional, Tuple
from telegram import Chat, ChatMember, ChatMemberUpdated, Update, ChatJoinRequest
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import (Application, ChatMemberHandler, ChatJoinRequestHandler,
                          CommandHandler, ContextTypes, MessageHandler, filters,
                          ConversationHandler)

# Telegram bot token from BotFather
TOKEN = os.environ["TOKEN"]
# GSheet Key for 'Lista de socios 2023 actualizada automáticamente'
SHEET_KEY = os.environ["SHEET_KEY"]
# Relevant columns from the GSheet
gs_name_col = 1
gs_dni_col = 3
gs_username_col = 12

# Import Google service account credentials
google_json = os.environ["GOOGLE_JSON"]
service_account_info = json.loads(google_json)
credentials = service_account.Credentials.from_service_account_info(service_account_info)
scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
creds_with_scope = credentials.with_scopes(scope)
# Authorize access to Google Sheets
gs_client = gspread.authorize(creds_with_scope)

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DNI = range(1)

def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member
    of the chat and whether the 'new_chat_member' is a member of the chat. Returns None, if
    the status didn't change.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member

async def greet_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets new users in chats and announces when someone leaves"""
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    member_name = update.chat_member.new_chat_member.user.mention_html()

    if not was_member and is_member:
        await update.effective_chat.send_message(
            f"¡Bienvenido/a al grupo, {member_name}!",
            parse_mode=ParseMode.HTML,
        )

async def handle_join_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the approval or decline of the new user joining the group"""
    # TODO: Hacer que el bot avise por el grupo de admins de lo que sucede
    request = update.chat_join_request

    name = request.from_user.first_name
    if request.from_user.last_name:
        name += ' ' + request.from_user.last_name

    text = f"¡Hola, {name}\! Has solicitado unirte al grupo *{request.chat.title}*\.\n\n"

    spreadsheet = gs_client.open_by_key(context.bot_data['sheet_key'])
    worksheet = spreadsheet.get_worksheet(0)

    # TODO: Hacer bien la lógica de los mensajes estos
    if request.from_user.username:
        re_pattern = re.compile(f"^(@|t\.me\/)?({request.from_user.username})[ ]*$")
        cell = worksheet.find(re_pattern,in_column=gs_username_col)
        if cell:
            text += f"He encontrado tu usuario _{request.from_user.username}_ en la "\
                    f"fila {cell.row} del Excel de socios activos\. Puedes entrar. 😊\n\n"
            await request.approve()
        else:
            text += f"Tu usuario _{request.from_user.username}_ no aparece en el "\
                    f"Excel de socios activos\. 🤨\n\n"
    else:
        text += f"Parece que no tienes nombre de usuario de Telegram\.\.\.\n\n"

    if request.from_user.last_name:
        re_pattern = re.compile(f"^({name})(.)*$")
        cell = worksheet.find(re_pattern,in_column=gs_name_col,case_sensitive=False)
        if cell:
            text += f"Tu nombre y apellidos \(_{cell.value}_\) aparecen en el Excel de socios\. 😊\n\n"
        else:
            text += f"Tu nombre y apellidos tampoco aparecen en el Excel de socios\. 🤔\n\n"
    else:
        text += f"Demasiada gente podría llamarse igual que tú\. Tu nombre asecas "\
                f"no me sirve para buscarte en la lista de socios\.\.\.\n\n"

    cell = worksheet.find(name,in_column=gs_username_col)
    if cell:
        text += f"Parece que tu nombre y apellidos coinciden con el usuario "\
                f"_{request.from_user.username}_ que introdujiste al inscribirte\.\.\. "\
                f"Daremos eso por bueno\.\n\n"
    else:
        text += f"Tu nombre y apellidos tampoco coinciden con el usuario que "\
                f"introdujiste al inscribirte\. 😞\n\n"

    text += f"Por favor, dime cuál es tu *DNI* \(sin guiones ni espacios\) para "\
            f"comprobar que eres socio\/a\."

    await context.bot.send_message(request.user_chat_id, text, ParseMode.MARKDOWN_V2)

    # await request.approve()
    # await request.decline()

    context.user_data['joining_chat_id'] = request.chat.id
    return DNI

async def input_dni(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the message containing the DNI of the user and checks it"""
    if not update.message.text:
        await update.message.reply_text("Por favor, escribe únicamente tu DNI sin guiones ni espacios.")
        return DNI

    match = re.search('[0-9A-Z]+', update.message.text.upper())
    if not match:
        await update.message.reply_text("Por favor, escribe únicamente tu DNI sin guiones ni espacios.")
        return DNI

    dni = match[0]
    spreadsheet = gs_client.open_by_key(context.bot_data['sheet_key'])
    worksheet = spreadsheet.get_worksheet(0)
    cell = worksheet.find(dni,in_column=gs_dni_col)
    chat_id = context.user_data.pop('joining_chat_id')
    if cell:
        name = worksheet.cell(cell.row, gs_name_col).value
        text = f"¡Bien\! Tu DNI _{dni}_ aparece asociado a _{name}_ en nuestra "\
               f"lista de socios activos\.\n\nYa tienes acceso al grupo\. 😁"
        await update.effective_user.approve_join_request(chat_id)
    else:
        text = f"Lo siento, pero tu DNI no aparece en nuestra lista de socios "\
                f"activos, así que no puedo dejarte acceder...\n\n"\
                f"Si realmente eres socio, esto puede deberse a que aún no se "\
                f"haya confirmado la recepción de la cuota de inscripción/renovación.\n\n"\
                f"Si has escrito mal tu DNI, puedes volver a solicitar unirte "\
                f"al grupo y volveré a ponerme en contacto contigo."
        text = escape_markdown(text, 2)
        await update.effective_user.decline_join_request(chat_id)
    await update.message.reply_text(text, ParseMode.MARKDOWN_V2)

    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    # Create the Application with my bot TOKEN
    application = Application.builder().token(TOKEN).build()

    # TODO: Make this an input of a command and make it persistent
    # https://github.com/python-telegram-bot/python-telegram-bot/wiki/Making-your-bot-persistent
    application.bot_data['sheet_key'] = SHEET_KEY

    # Handle members joining/leaving chats.
    application.add_handler(ChatMemberHandler(greet_chat_members, ChatMemberHandler.CHAT_MEMBER))

    # Handle members who want to join the group
    # application.add_handler(ChatJoinRequestHandler(handle_join_requests))
    conv_handler = ConversationHandler(
        entry_points=[ChatJoinRequestHandler(handle_join_requests)],
        states={
            DNI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_dni)],
        },
        fallbacks=[],
        per_chat=False
    )
    # TODO: Hacer que el bot sepa si alguien le ha bloqueado y avisar a los admins

    application.add_handler(conv_handler)

    # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, input_dni))

    # Run the bot until the user presses Ctrl-C
    # We pass 'allowed_updates' handle *all* updates including `chat_member` updates
    # To reset this, simply pass `allowed_updates=[]`
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()