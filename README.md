# FPUInvestiga Bot

**FPUInvestiga Bot** is a Telegram bot written in Python and built on the [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) API (v20.7).

The purpose of this bot is to control access to the Telegram group of FPU Investiga association members, letting in only active members collected in an associated Google spreadsheet. The bot itself can be found at [@FPUInvestiga_bot](https://t.me/fpuinvestiga_bot).
## Run locally

First, clone the project

```bash
git clone https://github.com/Pablo097/FPUInvestiga-bot.git
```

Go inside the project folder and install the dependencies through the `requirements.txt` file
```bash
pip install -r requirements.txt
```
In the folder where you have cloned the project (`FPUInvestiga-bot`), create a file named `.env` where the environment variables will be stored. The Telegram bot token is obtained talking to the [@BotFather](https://t.me/BotFather), and the Google API authentication information to gain access to the Drive spreadsheets is obtained following, for example, [this tutorial](https://www.datacamp.com/tutorial/how-to-analyze-data-in-google-sheets-with-python-a-step-by-step-guide). The content of the `.env` file must look like this (the `<...>` represents confidential data not shown here):
```
TOKEN="<your telegram bot token>"
GOOGLE_JSON={  "type": "service_account",  "project_id": "<...>",  "private_key_id": "<...>",  "private_key": "-----BEGIN PRIVATE KEY-----\n<...>\n-----END PRIVATE KEY-----\n",  "client_email": "<...>,  "client_id": "<...>",  "auth_uri": "<...>",  "token_uri": "<...>",  "auth_provider_x509_cert_url": "<...>",  "client_x509_cert_url": "<...>",  "universe_domain": "<...>"}
SHEET_KEY="<the active members google sheet ID>"
```
Finally, start the bot by running `debug_bot.py`.

## Contributing

Contributions are always welcome! You can fork the project and issue a pull request.
You can also directly contact me if you detect bugs or have any idea for improvement.


## Authors

- [Pablo Mateos Ruiz](https://github.com/Pablo097)


## License

[GPL 3.0](https://choosealicense.com/licenses/gpl-3.0/)
