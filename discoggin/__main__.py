import sys
import logging, logging.handlers
import optparse
import configparser
import json
import subprocess

import discord
import discord.app_commands

from .glk import create_metrics
from .glk import GlkState
from .markup import extract_command, content_to_markup, rebalance_output

popt = optparse.OptionParser(usage='python -m discoggin')

popt.add_option('--cmdsync',
                action='store_true', dest='cmdsync',
                help='upload slash commands to Discord')
popt.add_option('--logstream',
                action='store_true', dest='logstream',
                help='log to stdout rather than the configured file')

(opts, args) = popt.parse_args()

config = configparser.ConfigParser()
config.read('app.config')

bottoken = config['DEFAULT']['BotToken']
logfilepath = config['DEFAULT']['LogFile']

###
gamefile = '/Users/zarf/src/glk-dev/unittests/Advent.ulx'

if opts.logstream:
    loghandler = logging.StreamHandler(sys.stdout)
else:
    loghandler = logging.handlers.WatchedFileHandler(logfilepath)
logformatter = logging.Formatter('[%(levelname).1s %(asctime)s] %(message)s', datefmt='%b-%d %H:%M:%S')
loghandler.setFormatter(logformatter)

rootlogger = logging.getLogger()
rootlogger.addHandler(loghandler)
rootlogger.setLevel(logging.INFO)

class DiscogClient(discord.Client):
    def __init__(self):
        intents = discord.Intents(guilds=True, messages=True, guild_messages=True, dm_messages=True,  message_content=True)
        ### members? needs additional bot priv

        super().__init__(intents=intents)
        
        self.tree = discord.app_commands.CommandTree(self)

        self.tree.add_command(discord.app_commands.Command(
            name='start', callback=self.on_cmd_start,
            description='Start the current game'))
        self.tree.add_command(discord.app_commands.Command(
            name='stop', callback=self.on_cmd_stop,
            description='Stop the current game (force QUIT)'))
        self.tree.add_command(discord.app_commands.Command(
            name='status', callback=self.on_cmd_status,
            description='Display the status window'))

        self.glkstate = None  ###
        
    async def setup_hook(self):
        if opts.cmdsync:
            logging.info('syncing slash commands...')
            await self.tree.sync()

    async def on_ready(self):
        logging.info('We have logged in as %s', self.user)

    async def on_cmd_start(self, interaction):
        logging.info('slash command: start')
        ### content based on interaction.channel
        if self.glkstate is not None:
            await interaction.response.send_message('The game is already running.')
            return
        await interaction.response.send_message('Game is starting...')
        await self.run_turn(None, interaction.channel)
    
    async def on_cmd_stop(self, interaction):
        logging.info('slash command: stop')
        if self.glkstate is None:
            await interaction.response.send_message('The game is not running.')
            return
        self.glkstate = None
        await interaction.response.send_message('Game has been stopped.')

    async def on_cmd_status(self, interaction):
        logging.info('slash command: status')
        if self.glkstate is None:
            await interaction.response.send_message('The game is not running.')
            return
        chan = interaction.channel
        await interaction.response.send_message('Status line displayed.', ephemeral=True)
        outls = [ content_to_markup(val) for val in self.glkstate.statuswindat ]
        outls = rebalance_output(outls)
        for out in outls:
            if out.strip():
                await chan.send('|\n'+out)
        
    async def on_message(self, message):
        if message.author == self.user:
            return

        cmd = extract_command(message.content)
        if cmd is not None:
            if self.glkstate is None:
                await message.channel.send('The game is not running. (/start to start it.)')
                return
            logging.info('Command: %s', cmd) ###
            await self.run_turn(cmd, message.channel)

    async def run_turn(self, cmd, chan):
        if not chan:
            logging.warning('run_turn: channel not set')
            return
            
        if self.glkstate is None:
            if cmd is not None:
                logging.warning('Tried to send command when game was not running: %s', cmd)
                return
            
            update = {
                'type':'init', 'gen':0,
                'metrics': create_metrics(),
                'support': [ 'timer', 'hyperlinks' ],
            }
            indat = json.dumps(update)
            
            args = [ 'glulxer', '-singleturn', '--autosave', '--autodir', 'savedir', gamefile ]
        else:
            if cmd is None:
                logging.warning('Tried to send no command when game was running')
                return
                
            try:
                input = self.glkstate.construct_input(cmd)
                indat = json.dumps(input)
            except Exception as ex:
                await chan.send('Unable to construct input: %s' % (ex,))
                return
            
            args = [ 'glulxer', '-singleturn', '-autometrics', '--autosave', '--autorestore', '--autodir', 'savedir', gamefile ]

        try:
            proc = subprocess.Popen(
                args,
                bufsize=0,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            ### timeout parameter?
            (outdat, errdat) = proc.communicate((indat+'\n').encode(), timeout=2)
        except Exception as ex:
            logging.error('Interpreter exception: %s', ex, exc_info=ex)
            await chan.send('Interpreter exception: %s' % (ex,))
            return
            
        if errdat:
            await chan.send('Interpreter stderr: %s' % (errdat,))
            # but try to continue

        try:
            update = json.loads(outdat)
        except:
            await chan.send('Invalid JSON output: %s' % (outdat,))
            return

        if update.get('type') == 'error':
            msg = update.get('message', '???')
            await chan.send('Interpreter error: %s' % (msg,))
            return

        if self.glkstate is None:
            self.glkstate = GlkState()
        try:
            self.glkstate.accept_update(update)
        except Exception as ex:
            await chan.send('Update error: %s' % (ex,))
            return

        outls = [ content_to_markup(val) for val in self.glkstate.storywindat ]
        outls = rebalance_output(outls)
        for out in outls:
            if out.strip():
                await chan.send('>\n'+out)
        ### otherwise show status line? or something?
        
client = DiscogClient()

client.run(bottoken, log_handler=loghandler, log_formatter=logformatter)

