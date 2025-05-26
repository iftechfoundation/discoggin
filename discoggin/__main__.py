import sys
import logging, logging.handlers
import configparser
import json
import subprocess

import discord
import discord.app_commands

from .glk import create_metrics
from .glk import GlkState
from .markup import extract_command, content_to_markup

# Based on the discord.py library:
#    https://github.com/Rapptz/discord.py/

config = configparser.ConfigParser()
config.read('app.config')

bottoken = config['DEFAULT']['BotToken']
logfilepath = config['DEFAULT']['LogFile']

gamefile = '/Users/zarf/src/glk-dev/unittests/Advent.ulx'

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
        self.glkstate = None
        self.tree = discord.app_commands.CommandTree(self)

        @self.tree.command(name='hello', description='Greet the user')
        async def hellofunc(interaction):
            await self.on_cmd_hello(interaction)
        
    async def setup_hook(self):
        if False:
            logging.info('syncing slash commands...')
            await self.tree.sync()

    async def on_ready(self):
        logging.info('We have logged in as %s', self.user)

    async def on_cmd_hello(self, interaction):
        logging.info('slash command: hello')
        await interaction.response.send_message(f'Hi, {interaction.user.mention}')
    
    async def on_message(self, message):
        if message.author == self.user:
            return

        cmd = extract_command(message.content)
        if cmd is not None:
            logging.info('Command: %s', cmd) ###
            
            if self.glkstate is None:
                update = {
                    'type':'init', 'gen':0,
                    'metrics': create_metrics(),
                    'support': [ 'timer', 'hyperlinks' ],
                }
                cmd = json.dumps(update)
                
                args = [ 'glulxer', '-singleturn', '--autosave', '--autodir', 'savedir', gamefile ]
            else:
                raise Exception('### no followup')

            try:
                proc = subprocess.Popen(
                    args,
                    bufsize=0,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                ### timeout parameter?
                (outdat, errdat) = proc.communicate((cmd+'\n').encode(), timeout=2)
            except Exception as ex:
                logging.error('Interpreter exception: %s', ex, exc_info=ex)
                await message.channel.send('Interpreter exception: %s' % (ex,))
                return
                
            if errdat:
                await message.channel.send('Interpreter stderr: %s' % (errdat,))
                # but try to continue

            try:
                update = json.loads(outdat)
            except:
                await message.channel.send('Invalid JSON output: %s' % (outdat,))
                return

            if update.get('type') == 'error':
                msg = update.get('message', '???')
                await message.channel.send('Interpreter error: %s' % (msg,))
                return

            self.glkstate = GlkState()
            self.glkstate.accept_update(update)

            outls = [ content_to_markup(val) for val in self.glkstate.storywindat ]
            if outls:
                out = '\n'.join(outls)
                await message.channel.send(out)
    
        
client = DiscogClient(intents=intents)

client.run(bottoken, log_handler=loghandler, log_formatter=logformatter)

