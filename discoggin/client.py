import json
import subprocess
import logging
import sqlite3
import asyncio
import aiohttp

import discord
import discord.app_commands

from .glk import create_metrics
from .glk import GlkState
from .markup import extract_command, content_to_markup, rebalance_output
from .games import get_gamelist, get_gamemap, get_game_by_name, get_game_by_hash
from .games import download_game_url
from .sessions import get_sessions, get_session_by_id, get_available_session_for_hash, create_session, set_channel_session
from .sessions import get_playchannels, get_valid_playchannel, get_playchannel_for_session

###
gamefile = '/Users/zarf/src/glk-dev/unittests/Advent.ulx'

_appcmds = []

def appcmd(name, description):
    def decorator(func):
        _appcmds.append( (func.__name__, name, description) )
        return func
    return decorator

class DiscogClient(discord.Client):
    def __init__(self, config, cmdsync=False):
        self.config = config
        self.cmdsync = cmdsync

        self.autosavedir = config['DEFAULT']['AutoSaveDir']
        self.gamesdir = config['DEFAULT']['GamesDir']
        self.dbfile = config['DEFAULT']['DBFile']
        
        intents = discord.Intents(guilds=True, messages=True, guild_messages=True, dm_messages=True,  message_content=True)
        ### members? needs additional bot priv

        super().__init__(intents=intents)
        
        self.tree = discord.app_commands.CommandTree(self)

        for (key, name, description) in _appcmds:
            callback = getattr(self, key)
            cmd = discord.app_commands.Command(name=name, callback=callback, description=description)
            self.tree.add_command(cmd)

        self.httpsession = None
        self.glkstate = None  ###

        self.db = sqlite3.connect(self.dbfile)
        self.db.isolation_level = None   # autocommit


    async def setup_hook(self):
        headers = { 'user-agent': 'Discoggin-IF-Terp' }
        self.httpsession = aiohttp.ClientSession(headers=headers)
        
        if self.cmdsync:
            logging.info('syncing %d slash commands...', len(_appcmds))
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

    @appcmd('start', description='Start the current game')
    async def on_cmd_start(self, interaction):
        logging.info('slash command: start')
        ### content based on interaction.channel
        if self.glkstate is not None:
            await interaction.response.send_message('The game is already running.')
            return
        await interaction.response.send_message('Game is starting...')
        await self.run_turn(None, interaction.channel)
    
    @appcmd('stop', description='Stop the current game (force QUIT)')
    async def on_cmd_stop(self, interaction):
        logging.info('slash command: stop')
        if self.glkstate is None:
            await interaction.response.send_message('The game is not running.')
            return
        self.glkstate = None
        await interaction.response.send_message('Game has been stopped.')

    @appcmd('status', description='Display the status window')
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

    @appcmd('download', description='Download an game file for play')
    async def on_cmd_download(self, interaction, url:str):
        try:
            msg = await download_game_url(self, url)
            await interaction.response.send_message(msg)
        except Exception as ex:
            logging.error('Download: %s', ex, exc_info=ex)
            await interaction.response.send_message('Download error: %s' % (ex,))

    @appcmd('games', description='List downloaded games')
    async def on_cmd_gamelist(self, interaction):
        gamels = get_gamelist(self)
        if not gamels:
            await interaction.response.send_message('No games downloaded')
            return
        ls = [ 'Downloaded games available for play: (**/select** one)' ]
        for game in gamels:
            ls.append('- %s (%s)' % (game.filename, game.format,))
        val = '\n'.join(ls)
        ### is there a message size limit here?
        await interaction.response.send_message(val)
                
    @appcmd('sessions', description='List game sessions')
    async def on_cmd_sessionlist(self, interaction):
        sessls = get_sessions(self)
        if not sessls:
            await interaction.response.send_message('No game sessions in progress')
            return
        sessls.sort(key=lambda sess: sess.lastupdate)
        gamemap = get_gamemap(self)
        chanls = get_playchannels(self)
        chanmap = {}
        for playchan in chanls:
            if playchan.sessid:
                chanmap[playchan.sessid] = playchan
        ls = []
        for sess in sessls:
            game = gamemap.get(sess.hash)
            gamestr = game.filename if game else '???'
            playchan = chanmap.get(sess.sessid)
            chanstr = ''
            if playchan:
                chanstr = ' (playing in channel <#%s>)' % (playchan.chanid,)
            ls.append('- session %s: %s%s, %d moves, <t:%s:f>' % (sess.sessid, gamestr, chanstr, sess.movecount, sess.lastupdate,))
        val = '\n'.join(ls)
        ### is there a message size limit here?
        await interaction.response.send_message(val)
                
    @appcmd('newsession', description='Start a new game session in this channel')
    async def on_cmd_newsession(self, interaction, game:str):
        gamearg = game
        playchan = get_valid_playchannel(self, interaction=interaction)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        game = get_game_by_name(self, gamearg)
        if not game:
            await interaction.response.send_message('Game not found: "%s"' % (gamearg,))
            return
        session = create_session(self, game)
        set_channel_session(self, playchan, session)
        await interaction.response.send_message('Began a new session for "%s"' % (game.filename,))
        
    @appcmd('select', description='Select a game or session to play in this channel')
    async def on_cmd_select(self, interaction, game:str):
        gamearg = game
        playchan = get_valid_playchannel(self, interaction=interaction)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        session = get_session_by_id(self, gamearg)
        if session:
            prevchan = get_playchannel_for_session(self, session.sessid)
            if prevchan:
                if prevchan.chanid == playchan.chanid:
                    await interaction.response.send_message('This channel is already using session %d.' % (session.sessid,))
                else:
                    await interaction.response.send_message('Session %d is already being used in channel <#%s>.' % (session.sessid, prevchan.chanid,))
                return
            set_channel_session(self, playchan, session)
            game = get_game_by_hash(self, session.hash)
            if not game:
                await interaction.response.send_message('Activated session %s, but cannot find associated game' % (session.sessid,))
                return
            await interaction.response.send_message('Activated session %d for "%s"' % (session.sessid, game.filename,))
            return
            
        game = get_game_by_name(self, gamearg)
        if not game:
            await interaction.response.send_message('Game not found: "%s"' % (gamearg,))
            return
        ### if already on this game...
        session = get_available_session_for_hash(self, game.hash)
        if session:
            set_channel_session(self, playchan, session)
            await interaction.response.send_message('Activated session %d for "%s"' % (session.sessid, game.filename,))
            return
        session = create_session(self, game)
        set_channel_session(self, playchan, session)
        await interaction.response.send_message('Began a new session for "%s"' % (game.filename,))
        
    async def on_message(self, message):
        if message.author == self.user:
            return

        cmd = extract_command(message.content)
        if cmd is not None:
            if self.glkstate is None:
                await message.channel.send('The game is not running. (**/start** to start it.)')
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
