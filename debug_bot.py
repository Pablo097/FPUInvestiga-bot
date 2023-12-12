from dotenv import load_dotenv

if load_dotenv():
    print("Environment variables succesfully imported")
else:
    print("Failed importing environment variables")

import bot
bot.main()
