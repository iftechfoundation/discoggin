import json
import subprocess
import logging
import asyncio
import aiohttp

import discord
import discord.app_commands

from .glk import create_metrics
from .glk import GlkState
from .markup import extract_command, content_to_markup, rebalance_output

###
gamefile = '/Users/zarf/src/glk-dev/unittests/Advent.ulx'


class DiscogClient(discord.Client):
    def __init__(self, config, cmdsync=False):
        self.config = config
        self.cmdsync = cmdsync

        self.autosavedir = config['DEFAULT']['AutoSaveDir']
        self.gamesdir = config['DEFAULT']['GamesDir']
        
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
        self.tree.add_command(discord.app_commands.Command(
            name='download', callback=self.on_cmd_download,
            description='Download an IF game file for play'))

        self.httpsession = None
        self.task_download = None  ### use a set()? 
        self.glkstate = None  ###

    async def setup_hook(self):
        headers = { 'user-agent': 'Discoggin-IF-Terp' }
        self.httpsession = aiohttp.ClientSession(headers=headers)
        
        if self.cmdsync:
            logging.info('syncing slash commands...')
            await self.tree.sync()

    async def close(self):
        logging.warning('Shutting down...')
        
        if self.httpsession:
            await self.httpsession.close()
            self.httpsession = None
            
        await super().close()
        
    def launch_coroutine(self, coro, label='task'):
        """Convenience function to begin an asynchronous task and report
        any exception that occurs. This returns a task object. (You might
        want to cancel it later.)
        """
        task = self.loop.create_task(coro)
        def callback(future):
            if future.cancelled():
                return
            ex = future.exception()
            if ex is not None:
                logging.error('%s: %s', label, ex, exc_info=ex)
        task.add_done_callback(callback)
        return task

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

    async def on_cmd_download(self, interaction, url:str):
        logging.info('slash command: download: %s', url)
        if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
            await interaction.response.send_message('Download URL must start with `http://` or `https://`.', ephemeral=True)
            return

        if self.task_download:
            await interaction.response.send_message('Already downloading a game; please wait a moment and try again.', ephemeral=True)
            return

        ### maybe this should all happen within the cmd
        self.task_download = self.launch_coroutine(self.download_game(url, interaction.channel), 'download_game')
        def callback(future):
            self.task_download = None
        self.task_download.add_done_callback(callback)
        
        await interaction.response.send_message('Downloading %s...' % (url,))

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

    async def download_game(self, url, chan):
        logging.info('Downloading %s', url)
        async with self.httpsession.get(url) as resp:
            if resp.status != 200:
                await chan.send('Download HTTP error: %s %s: %s' % (resp.status, resp.reason, url))
                return
            totallen = 0
            with open('games/tmp', 'wb') as outfl:
                async for dat in resp.content.iter_chunked(4096):
                    totallen += len(dat)
                    outfl.write(dat)
        
        await chan.send('Downloaded %s (%d bytes)' % (url, totallen,))

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
            
            args = [ 'glulxer', '-singleturn', '--autosave', '--autodir', self.autosavedir, gamefile ]
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
            
            args = [ 'glulxer', '-singleturn', '-autometrics', '--autosave', '--autorestore', '--autodir', self.autosavedir, gamefile ]

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
