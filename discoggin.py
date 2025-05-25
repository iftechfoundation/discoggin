import configparser
import discord
import logging

# Based on the discord.py library:
#    https://github.com/Rapptz/discord.py/


config = configparser.ConfigParser()
config.read('app.config')

bottoken = config['DEFAULT']['BotToken']

### handler will be WatchedFileHandler
logging.basicConfig(
    format = '[%(levelname).1s %(asctime)s] %(message)s',
    datefmt = '%b-%d %H:%M:%S',
    level = logging.INFO,
    # handlers = [ loghandler ],
)

intents = discord.Intents(messages=True, guild_messages=True, dm_messages=True,  message_content=True)
### members? needs additional bot priv

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    logging.info('We have logged in as %s', client.user)

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('>'):
        logging.info('Command: %r', message.content)
        await message.channel.send('Command received.')

client.run(bottoken)  ### log_handler=...
