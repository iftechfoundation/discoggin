import os, os.path
import time
import json
import collections
import logging
import sqlite3
import asyncio
import asyncio.subprocess
import aiohttp

import discord
import discord.app_commands

from .markup import extract_command, content_to_markup, rebalance_output, escape
from .games import GameFile
from .games import get_gamelist, get_gamemap, get_game_by_name, get_game_by_hash, get_game_by_channel
from .games import download_game_url
from .games import format_interpreter_args
from .sessions import get_sessions, get_session_by_id, get_sessions_for_server, get_available_session_for_hash, create_session, set_channel_session, update_session_movecount
from .sessions import get_playchannels, get_playchannels_for_server, get_valid_playchannel, get_playchannel_for_session
from .glk import create_metrics
from .glk import parse_json
from .glk import ContentLine
from .glk import GlkState, get_glkstate_for_session, put_glkstate_for_session
from .glk import stanza_reader, storywindat_from_stanza
from .attlist import AttachList

_appcmds = []

def appcmd(name, description, argdesc=None):
    """A decorator for slash commands.
    The discord module provides such a decorator but I don't like it.
    I wrote this one instead.
    """
    def decorator(func):
        _appcmds.append( (func.__name__, name, description, argdesc) )
        return func
    return decorator

class DiscogClient(discord.Client):
    """Our Discord client class.
    """
    def __init__(self, config):
        self.config = config
        self.cmdsync = False

        self.logger = logging.getLogger('cli')

        self.dbfile = config['DEFAULT']['DBFile']
        
        # These are absolutized because we will pass them to the interpreter,
        # which runs in a subdirectory.
        self.autosavedir = os.path.abspath(config['DEFAULT']['AutoSaveDir'])
        self.savefiledir = os.path.abspath(config['DEFAULT']['SaveFileDir'])
        self.gamesdir = os.path.abspath(config['DEFAULT']['GamesDir'])
        self.terpsdir = os.path.abspath(config['DEFAULT']['InterpretersDir'])
        
        intents = discord.Intents(guilds=True, messages=True, guild_messages=True, dm_messages=True, message_content=True)

        super().__init__(intents=intents)

        self.playchannels = set()  # of gckeys
        self.inflight = set()  # of session ids
        self.attachments = AttachList()

        # Container for slash commands.
        self.tree = discord.app_commands.CommandTree(self)

        # Add all the slash commands noted by the @appcmd decorator.
        for (key, name, description, argdesc) in _appcmds:
            callback = getattr(self, key)
            cmd = discord.app_commands.Command(name=name, callback=callback, description=description)
            if argdesc:
                for akey, adesc in argdesc.items():
                    cmd._params[akey].description = adesc
            self.tree.add_command(cmd)

        # Our async HTTP client session.
        # We will set this up in setup_hook.
        self.httpsession = None

        # Open the sqlite database.
        self.db = sqlite3.connect(self.dbfile)
        self.db.isolation_level = None   # autocommit

    async def print_lines(self, outls, chan, prefix=None):
        """Print a bunch of lines (paragraphs) to the Discord channel.
        They should already be formatted in Discord markup.
        Add prefix if provided.
        ### the prefix must be shorter than the safety margin
        """
        # Optimize to fit in the fewest number of Discord messages.
        outls = rebalance_output(outls)

        first = True
        for out in outls:
            if not first:
                # Short sleep to avoid rate-limiting.
                await asyncio.sleep(0.25)
            if prefix:
                out = prefix+out
            await chan.send(out)
            first = False

    async def setup_hook(self):
        """Called when the client is starting up. We have not yet connected
        to Discord, but we have entered the async regime.
        """
        # Create the HTTP session, which must happen inside the async
        # event loop.
        headers = { 'user-agent': 'Discoggin-IF-Terp' }
        self.httpsession = aiohttp.ClientSession(headers=headers)

        self.cache_playchannels()
        
        if self.cmdsync:
            # Push our slash commands to Discord. We only need to do
            # this once after adding or modifying a slash command.
            # (No, we're not connected to Discord yet. This uses web
            # RPC calls rather than the websocket.)
            self.logger.info('Syncing %d slash commands...', len(_appcmds))
            await self.tree.sync()
            # The cmdsync option was set by a command-line command.
            # Shut down now that it's done.
            await self.close()

    async def close(self):
        """Called when the client is shutting down. We override this to
        finalize resources.
        """
        self.logger.warning('Shutting down...')
        
        if self.httpsession:
            await self.httpsession.close()
            self.httpsession = None

        if self.db:
            self.db.close()
            self.db = None
            
        await super().close()
        
    async def on_ready(self):
        """We have finished connecting to Discord.
        (Docs recommend against doing Discord API calls from here.)
        """
        self.logger.info('Logged in as %s', self.user)

    def cache_playchannels(self):
        """Grab the list of valid playchannels and store it in memory.
        We will use this for fast channel-checking.
        """
        ls = get_playchannels(self)
        self.playchannels.clear()
        for chan in ls:
            self.playchannels.add(chan.gckey)
        
    # Slash command implementations.
        
    @appcmd('start', description='Start the current game')
    async def on_cmd_start(self, interaction):
        """/start
        """
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        if not playchan.game:
            await interaction.response.send_message('No game is being played in this channel.')
            return
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate and glkstate.islive():
            await interaction.response.send_message('The game is already running.')
            return
        await interaction.response.send_message('Game is starting...')
        
        if playchan.sessid in self.inflight:
            playchan.logger().warning('run_turn wrapper (s%s): command in flight', playchan.sessid)
            return
        self.inflight.add(playchan.sessid)
        try:
            await self.run_turn(None, interaction.channel, playchan, None)
        finally:
            self.inflight.discard(playchan.sessid)
    
    @appcmd('forcequit', description='Force the current game to end')
    async def on_cmd_stop(self, interaction):
        """/forcequit
        """
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        if not playchan.game:
            await interaction.response.send_message('No game is being played in this channel.')
            return
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate is None or not glkstate.islive():
            await interaction.response.send_message('The game is not running.')
            return
        # We delete the GlkState entirely, rather than messing with the
        # exit flag. This lets us recover from a corrupted GlkState or
        # autosave entry.
        playchan.logger().info('game force-quit')
        put_glkstate_for_session(self, playchan.session, None)
        await interaction.response.send_message('Game has been stopped. (**/start** to restart it.)')

    @appcmd('files', description='List the save files for the current session')
    async def on_cmd_listfiles(self, interaction):
        """/files
        """
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        savefiledir = os.path.join(self.savefiledir, playchan.session.sessdir)
        if not os.path.exists(savefiledir):
            files = []
        else:
            files = [ ent for ent in os.scandir(savefiledir) if ent.is_file() ]
        if not files:
            await interaction.response.send_message('No files for the current session ("%s")' % (playchan.game.filename,))
            return
        files.sort(key=lambda ent: ent.name)
        ls = [ 'Files for the current session ("%s"):' % (playchan.game.filename,) ]
        for ent in files:
            timeval = int(ent.stat().st_mtime)
            ls.append('- %s <t:%s:f>' % (escape(ent.name), timeval,))
        await interaction.response.send_message('\n'.join(ls))
        
    @appcmd('status', description='Display the status window')
    async def on_cmd_status(self, interaction):
        """/status
        """
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        if not playchan.game:
            await interaction.response.send_message('No game is being played in this channel.')
            return
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate is None:
            # Actually we can view the status line of an exited game.
            await interaction.response.send_message('The game is not running.')
            return
        chan = interaction.channel
        await interaction.response.send_message('Status line displayed.', ephemeral=True)
        outls = [ content_to_markup(val) for val in glkstate.statuswindat ]
        await self.print_lines(outls, chan, '|\n')

    @appcmd('recap', description='Recap the last few commands',
            argdesc={ 'count':'Number of commands to recap' })
    async def on_cmd_recap(self, interaction, count:int=3):
        """/recap NUM
        """
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        if not playchan.game:
            await interaction.response.send_message('No game is being played in this channel.')
            return
        
        # At least one, but no more than ten, please
        count = min(10, count)
        count = max(1, count)

        playchan.logger().info('recap %d', count)
            
        autosavedir = os.path.join(self.autosavedir, playchan.session.sessdir)
        trapath = os.path.join(autosavedir, 'transcript.glktra')

        if not os.path.exists(trapath):
            await interaction.response.send_message('No transcript is available.')
            return

        # Fake in the initial prompt...
        storywindat = [ ContentLine('>') ]
        try:
            reader = stanza_reader(trapath)
            # tail recipe from itertools docs
            tailreader = iter(collections.deque(reader, maxlen=count))
            for stanza in tailreader:
                storywindat_from_stanza(stanza, storywindat=storywindat)
        except Exception as ex:
            self.logger.error('Transcript: %s', ex, exc_info=ex)
            await interaction.response.send_message('Transcript error: %s' % (ex,))
            return
        
        await interaction.response.send_message('Recapping last %d commands.' % (count,))
        
        # Display the output.
        outls = [ content_to_markup(val) for val in storywindat ]
        await self.print_lines(outls, interaction.channel, 'RECAP\n')
        
    @appcmd('install', description='Download and install a game file for play',
            argdesc={ 'url':'Game file URL' })
    async def on_cmd_install(self, interaction, url:str):
        """/install URL
        """
        playchan = get_valid_playchannel(self, interaction=interaction)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return

        filename = None
        
        if '/' not in url:
            # Special case
            if url == '?':
                attls = self.attachments.getlist(interaction.channel)
                if not attls:
                    await interaction.response.send_message('No recent file uploads to this channel.')
                    return
                attls.sort(key=lambda att:-att.timestamp)
                ls = [ 'Recently uploaded files:' ]
                for att in attls:
                    ls.append('- %s, <t:%s:f>' % (att.filename, int(att.timestamp),))
                val = '\n'.join(ls)
                ### is there a message size limit here?
                await interaction.response.send_message(val)
                return
                    
            att = self.attachments.findbyname(url, interaction.channel)
            if not att:
                await interaction.response.send_message('You must name a URL or a recently uploaded file.')
                return
            url = att.url
            filename = att.filename
            # continue...
        
        try:
            res = await download_game_url(self, url, filename)
        except Exception as ex:
            self.logger.error('Download: %s', ex, exc_info=ex)
            await interaction.response.send_message('Download error: %s' % (ex,))
        if isinstance(res, str):
            await interaction.response.send_message(res)
            return
        
        game = res
        if not isinstance(res, GameFile):
            await interaction.response.send_message('download_game_url: not a game')
            return

        session = create_session(self, game, interaction.guild_id)
        set_channel_session(self, playchan, session)
        session.logger().info('installed "%s" in #%s', game.filename, playchan.channame)
        await interaction.response.send_message('Downloaded "%s" and began a new session. (**/start** to start the game.)' % (game.filename,))

    @appcmd('games', description='List downloaded games')
    async def on_cmd_gamelist(self, interaction):
        """/games
        """
        gamels = get_gamelist(self)
        if not gamels:
            await interaction.response.send_message('No games are installed. (**/install URL** to install one.)')
            return
        ls = [ 'Downloaded games available for play: (**/select** one)' ]
        for game in gamels:
            ls.append('- %s (%s)' % (game.filename, game.format,))
        val = '\n'.join(ls)
        ### is there a message size limit here?
        await interaction.response.send_message(val)
                
    @appcmd('sessions', description='List game sessions')
    async def on_cmd_sessionlist(self, interaction):
        """/sessions
        """
        sessls = get_sessions_for_server(self, interaction.guild_id)
        if not sessls:
            await interaction.response.send_message('No game sessions are in progress.')
            return
        sessls.sort(key=lambda sess: -sess.lastupdate)
        gamemap = get_gamemap(self)
        chanls = get_playchannels_for_server(self, interaction.guild_id)
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

    @appcmd('channels', description='List channels that we can play on')
    async def on_cmd_channellist(self, interaction):
        """/channels
        This also re-checks the valid channel list. This is a hack.
        (We should have a way for the command-line API to tell the
        running instance to recache.)
        """
        self.cache_playchannels()
        chanls = get_playchannels_for_server(self, interaction.guild_id, withgame=True)
        if not chanls:
            await interaction.response.send_message('Discoggin is not available on this Discord server.')
            return
        ls = []
        for playchan in chanls:
            gamestr = ''
            if playchan.game:
                gamestr = ': %s, %d moves, <t:%s:f>' % (playchan.game.filename, playchan.session.movecount, playchan.session.lastupdate,)
            ls.append('- <#%s>%s' % (playchan.chanid, gamestr))
        val = '\n'.join(ls)
        ### is there a message size limit here?
        await interaction.response.send_message(val)
        
    @appcmd('newsession', description='Start a new game session in this channel',
            argdesc={ 'game':'Game name' })
    async def on_cmd_newsession(self, interaction, game:str):
        """/newsession GAME
        """
        gamearg = game
        playchan = get_valid_playchannel(self, interaction=interaction)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        game = get_game_by_name(self, gamearg)
        if not game:
            await interaction.response.send_message('Game not found: "%s"' % (gamearg,))
            return
        session = create_session(self, game, interaction.guild_id)
        set_channel_session(self, playchan, session)
        session.logger().info('new session for "%s" in #%s', game.filename, playchan.channame)
        await interaction.response.send_message('Began a new session for "%s" (**/start** to start the game.)' % (game.filename,))
        # No status line, game hasn't started yet
        
    @appcmd('select', description='Select a game or session to play in this channel',
            argdesc={ 'game':'Game name or session number' })
    async def on_cmd_select(self, interaction, game:str):
        """/select [ GAME | SESSION ]
        """
        gamearg = game
        playchan = get_valid_playchannel(self, interaction=interaction)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        
        try:
            gameargint = int(gamearg)
        except:
            gameargint = None
        if gameargint is not None:
            await self.on_cmd_select_session(interaction, playchan, gameargint)
        else:
            await self.on_cmd_select_game(interaction, playchan, gamearg)
            
    async def on_cmd_select_game(self, interaction, playchan, gamearg):
        """/select GAME (a game name)
        This is called by on_cmd_select(). It is responsible for responding
        to the interaction.
        """
        game = get_game_by_name(self, gamearg)
        if not game:
            await interaction.response.send_message('Game not found: "%s"' % (gamearg,))
            return
        curgame = get_game_by_channel(self, playchan.gckey)
        if curgame and game.hash == curgame.hash:
            await interaction.response.send_message('This channel is already playing "%s".' % (curgame.filename,))
            return
            
        session = get_available_session_for_hash(self, game.hash, interaction.guild_id)
        if session:
            set_channel_session(self, playchan, session)
            session.logger().info('selected "%s" in #%s', game.filename, playchan.channame)
            await interaction.response.send_message('Activated session %d for "%s"' % (session.sessid, game.filename,))
            # Display the status line of this session
            glkstate = get_glkstate_for_session(self, session)
            if glkstate:
                chan = interaction.channel
                outls = [ content_to_markup(val) for val in glkstate.statuswindat ]
                await self.print_lines(outls, chan, '|\n')
            return
        session = create_session(self, game, interaction.guild_id)
        set_channel_session(self, playchan, session)
        session.logger().info('new session for "%s" in #%s', game.filename, playchan.channame)
        await interaction.response.send_message('Began a new session for "%s" (**/start** to start the game.)' % (game.filename,))
        # No status line, game hasn't started yet

    async def on_cmd_select_session(self, interaction, playchan, sessid):
        """/select SESSION (a session number)
        This is called by on_cmd_select(). It is responsible for responding
        to the interaction.
        """
        session = get_session_by_id(self, sessid)
        if not session or session.gid != interaction.guild_id:
            await interaction.response.send_message('No session %d.' % (sessid,))
            return
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
            playchan.logger().warning('activated session, but could not find game')
            await interaction.response.send_message('Activated session %s, but cannot find associated game' % (session.sessid,))
            return
        session.logger().info('selected "%s" in #%s', game.filename, playchan.channame)
        await interaction.response.send_message('Activated session %d for "%s"' % (session.sessid, game.filename,))
        # Display the status line of this session
        glkstate = get_glkstate_for_session(self, session)
        if glkstate:
            chan = interaction.channel
            outls = [ content_to_markup(val) for val in glkstate.statuswindat ]
            await self.print_lines(outls, chan, '|\n')
        
    async def on_message(self, message):
        """Event handler for regular Discord chat messages.
        We will respond to messages that look like ">GET LAMP".
        """
        if message.author == self.user:
            # silently ignore messages we sent
            return

        playchan = get_valid_playchannel(self, message=message, withgame=True)
        if not playchan:
            # silently ignore messages in non-play channels
            return

        if message.attachments:
            # keep track of file attachments
            for obj in message.attachments:
                self.attachments.tryadd(obj, message.channel)
        
        cmd = extract_command(message.content)
        if not cmd:
            # silently ignore messages that don't look like commands
            # but record the message as a comment!
            self.record_comment(message, playchan)
            return
        
        if not playchan.game:
            await message.channel.send('No game is being played in this channel.')
            return
        
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate is None or not glkstate.islive():
            await message.channel.send('The game is not running. (**/start** to start it.)')
            return

        if playchan.sessid in self.inflight:
            playchan.logger().warning('run_turn wrapper (s%s): command in flight', playchan.sessid)
            return
        self.inflight.add(playchan.sessid)
        try:
            await self.run_turn(cmd, message.channel, playchan, glkstate)
        finally:
            self.inflight.discard(playchan.sessid)

    def record_comment(self, message, playchan):
        if not playchan.sessid:
            return
        if not message.author:
            return
        val = message.content.strip()
        if not val:
            return
        text = '%s: %s' % (message.author.name, val,)
        
        outputtime = int(time.time() * 1000)
        tradat = {
            "format": "comment",
            "sessionId": str(playchan.sessid),
            "text": text,
            "timestamp": outputtime
        }
        try:
            autosavedir = os.path.join(self.autosavedir, playchan.session.sessdir)
            if not os.path.exists(autosavedir):
                os.mkdir(autosavedir)
            
            trapath = os.path.join(autosavedir, 'transcript.glktra')
            with open(trapath, 'a') as outfl:
                json.dump(tradat, outfl)
                outfl.write('\n')
        except Exception as ex:
            logger.warning('Failed to write comment: %s', ex, exc_info=ex)


    async def run_turn(self, cmd, chan, playchan, glkstate):
        """Execute a turn by invoking an interpreter.
        The cmd and glkstate arguments should be None for the initial turn
        (starting the game).
        We always set sessid in the inflight set before calling this,
        and clear it after this completes. This lets us avoid invoking
        two turns on the same session at the same time.
        """
        logger = playchan.logger()
        
        if not chan:
            logger.warning('run_turn: channel not set')
            return

        inputtime = int(time.time() * 1000)
        firsttime = (glkstate is None or not glkstate.islive())

        gamefile = os.path.join(self.gamesdir, playchan.game.hash, playchan.game.filename)
        if not os.path.exists(gamefile):
            logger.error('run_turn: game file not found: %s', gamefile)
            await chan.send('Error: The game file seems to be missing.')
            return

        autosavedir = os.path.join(self.autosavedir, playchan.session.sessdir)
        if not os.path.exists(autosavedir):
            os.mkdir(autosavedir)
            
        savefiledir = os.path.join(self.savefiledir, playchan.session.sessdir)
        if not os.path.exists(savefiledir):
            os.mkdir(savefiledir)

        iargs, ienv = format_interpreter_args(playchan.game.format, firsttime, terpsdir=self.terpsdir, gamefile=gamefile, savefiledir=savefiledir, autosavedir=autosavedir)
        if iargs is None:
            logger.warning('run_turn: unknown format: %s', playchan.game.format)
            await chan.send('Error: No known interpreter for this format (%s)' % (playchan.game.format,))
            return

        # Inherit env vars
        allenv = os.environ.copy()
        if ienv:
            allenv.update(ienv)
        
        input = None
        extrainput = None
        
        if firsttime:
            # Game-start case.
            if cmd is not None:
                logger.warning('run_turn: tried to send command when game was not running: %s', cmd)
                return

            playchan.logger().info('game started')
            
            # Fresh state.
            glkstate = GlkState()

            update = {
                'type':'init', 'gen':0,
                'metrics': create_metrics(),
                'support': [ 'timer', 'hyperlinks' ],
            }
            indat = json.dumps(update)
        else:
            # Regular turn case.
            if cmd is None:
                logger.warning('run_turn: tried to send no command when game was running')
                return
                
            playchan.logger().info('>%s', cmd)
            
            try:
                input = glkstate.construct_input(cmd)
                indat = json.dumps(input)
            except Exception as ex:
                logger.error('Unable to construct input: %s', ex, exc_info=ex)
                await chan.send('Unable to construct input: %s' % (ex,))
                return

            if input.get('type') == 'specialresponse' and input.get('response') == 'fileref_prompt':
                extrainput = cmd

        # Launch the interpreter, push an input event into it, and then pull
        # an update out.
        try:
            async def func():
                proc = await asyncio.create_subprocess_exec(
                    *iargs,
                    env=allenv,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
                return await proc.communicate((indat+'\n').encode())
            (outdat, errdat) = await asyncio.wait_for(func(), 5)
        except TimeoutError:
            logger.error('Interpreter error: Command timed out')
            await chan.send('Interpreter error: Command timed out.')
            return
        except Exception as ex:
            logger.error('Interpreter exception: %s', ex, exc_info=ex)
            await chan.send('Interpreter exception: %s' % (ex,))
            return
            
        if errdat:
            await chan.send('Interpreter stderr: %s' % (errdat,))
            # but try to continue

        try:
            (update, errorls) = parse_json(outdat)
        except json.JSONDecodeError:
            try:
                outstr = outdat.decode()
            except:
                outstr = str(outdat)
            logger.error('Invalid JSON output: %r', outstr)
            await chan.send('Invalid JSON output: %s' % (outstr[:160],))
            return
        except Exception as ex:
            logger.error('JSON decode exception: %s', ex, exc_info=ex)
            await chan.send('JSON decode exception: %s' % (ex,))
            return

        # Display errorls, which contains the contents of JSON-encoded
        # error stanza(s). But don't exit just because we got errors.
        for msg in errorls:
            logger.error('Interpreter error message: %s', msg)
        outls = [ 'Interpreter error: %s' % (msg,) for msg in errorls ]
        await self.print_lines(outls, chan)

        if update is None:
            # If we didn't get any *non*-errors, that's a reason to exit.
            # But make sure we report at least one error.
            if not errorls:
                logger.error('Interpreter error: no update')
                await chan.send('Interpreter error: no update')
            return

        # Update glkstate with the output.
        try:
            glkstate.accept_update(update, extrainput)
        except Exception as ex:
            logger.error('Update error: %s', ex, exc_info=ex)
            await chan.send('Update error: %s' % (ex,))
            return

        put_glkstate_for_session(self, playchan.session, glkstate)

        update_session_movecount(self, playchan.session)

        outputtime = int(time.time() * 1000)
        tradat = {
            "format": "glkote",
            "input": input,
            "output": update,
            "sessionId": str(playchan.sessid),
            "label": playchan.game.filename,
            "timestamp": inputtime,
            "outtimestamp": outputtime
        }
        try:
            trapath = os.path.join(autosavedir, 'transcript.glktra')
            with open(trapath, 'a') as outfl:
                json.dump(tradat, outfl)
                outfl.write('\n')
        except Exception as ex:
            logger.warning('Failed to write transcript: %s', ex, exc_info=ex)

        # Display the output.
        outls = [ content_to_markup(val) for val in glkstate.storywindat ]
        printcount = sum([ len(out) for out in outls ])
        await self.print_lines(outls, chan, '>\n')

        if printcount <= 4:
            # No story output, or not much. Try showing the status line.
            outls = [ content_to_markup(val) for val in glkstate.statuswindat ]
            printcount = sum([ len(out) for out in outls ])
            await self.print_lines(outls, chan, '|\n')

        if printcount <= 4:
            await chan.send('(no game output)')

        if glkstate.exited:
            await chan.send('The game has exited. (**/start** to restart it.)')
            
