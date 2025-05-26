import logging, logging.handlers
import configparser

import discord
import discord.app_commands

# Based on the discord.py library:
#    https://github.com/Rapptz/discord.py/


config = configparser.ConfigParser()
config.read('app.config')

bottoken = config['DEFAULT']['BotToken']
logfilepath = config['DEFAULT']['LogFile']


loghandler = logging.handlers.WatchedFileHandler(logfilepath)
logformatter = logging.Formatter('[%(levelname).1s %(asctime)s] %(message)s', datefmt='%b-%d %H:%M:%S')
loghandler.setFormatter(logformatter)

rootlogger = logging.getLogger()
rootlogger.addHandler(loghandler)
rootlogger.setLevel(logging.INFO)

intents = discord.Intents(guilds=True, messages=True, guild_messages=True, dm_messages=True,  message_content=True)
### members? needs additional bot priv

class DiscogClient(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        if False:
            logging.info('syncing slash commands...')
            await self.tree.sync()

def build_client(client):

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
    
    
    @client.tree.command()
    async def hello(interaction):
        """Says hello!"""
        logging.info('slash command: hello')
        await interaction.response.send_message(f'Hi, {interaction.user.mention}')
    
        
client = DiscogClient(intents=intents)
build_client(client)

client.run(bottoken, log_handler=loghandler, log_formatter=logformatter)

