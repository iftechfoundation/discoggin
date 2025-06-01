import os, os.path
import json
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
from .sessions import get_sessions, get_session_by_id, get_available_session_for_hash, create_session, set_channel_session, update_session_movecount
from .sessions import get_playchannels, get_playchannels_for_server, get_valid_playchannel, get_playchannel_for_session
from .glk import create_metrics
from .glk import parse_json
from .glk import GlkState, get_glkstate_for_session, put_glkstate_for_session

_appcmds = []

def appcmd(name, description):
    """A decorator for slash commands.
    The discord module provides such a decorator but I don't like it.
    I wrote this one instead.
    """
    def decorator(func):
        _appcmds.append( (func.__name__, name, description) )
        return func
    return decorator

class DiscogClient(discord.Client):
    """Our Discord client class.
    """
    def __init__(self, config, cmdsync=False):
        self.config = config
        self.cmdsync = cmdsync

        self.autosavedir = config['DEFAULT']['AutoSaveDir']
        self.savefiledir = config['DEFAULT']['SaveFileDir']
        self.gamesdir = config['DEFAULT']['GamesDir']
        self.dbfile = config['DEFAULT']['DBFile']
        
        intents = discord.Intents(guilds=True, messages=True, guild_messages=True, dm_messages=True, message_content=True)

        super().__init__(intents=intents)

        self.inflight = set()  # of session ids

        # Container for slash commands.
        self.tree = discord.app_commands.CommandTree(self)

        # Add all the slash commands noted by the @appcmd decorator.
        for (key, name, description) in _appcmds:
            callback = getattr(self, key)
            cmd = discord.app_commands.Command(name=name, callback=callback, description=description)
            self.tree.add_command(cmd)

        # Our async HTTP client session.
        # We will set this up in setup_hook.
        self.httpsession = None

        # Open the sqlite database.
        self.db = sqlite3.connect(self.dbfile)
        self.db.isolation_level = None   # autocommit

    async def setup_hook(self):
        """Called when the client is starting up. We have not yet connected
        to Discord, but we have entered the async regime.
        """
        # Create the HTTP session, which must happen inside the async
        # event loop.
        headers = { 'user-agent': 'Discoggin-IF-Terp' }
        self.httpsession = aiohttp.ClientSession(headers=headers)
        
        if self.cmdsync:
            # Push our slash commands to Discord. We only need to do
            # this once after adding or modifying a slash command.
            # (No, we're not connected to Discord yet. This uses web
            # RPC calls rather than the websocket.)
            logging.info('Syncing %d slash commands...', len(_appcmds))
            await self.tree.sync()

    async def close(self):
        """Called when the client is shutting down. We override this to
        finalize resources.
        """
        logging.warning('Shutting down...')
        
        if self.httpsession:
            await self.httpsession.close()
            self.httpsession = None

        if self.db:
            self.db.close()
            self.db = None
            
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
        """We have finished connecting to Discord.
        (Docs recommend against doing Discord API calls from here.)
        """
        logging.info('Logged in as %s', self.user)

    # Slash command implementations.
        
    @appcmd('start', description='Start the current game')
    async def on_cmd_start(self, interaction):
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        if not playchan.game:
            await interaction.response.send_message('No game is being played in this channel.')
            return
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate is not None:
            await interaction.response.send_message('The game is already running.')
            return
        await interaction.response.send_message('Game is starting...')
        
        if playchan.sessid in self.inflight:
            logging.warning('run_turn wrapper (s%s): command in flight', playchan.sessid)
            return
        self.inflight.add(playchan.sessid)
        try:
            await self.run_turn(None, interaction.channel, playchan, None)
        finally:
            self.inflight.discard(playchan.sessid)
    
    @appcmd('forcequit', description='Force the current game to end')
    async def on_cmd_stop(self, interaction):
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        if not playchan.game:
            await interaction.response.send_message('No game is being played in this channel.')
            return
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate is None:
            await interaction.response.send_message('The game is not running.')
            return
        put_glkstate_for_session(self, playchan.session, None)
        await interaction.response.send_message('Game has been stopped. (**/start** to restart it.)')

    @appcmd('files', description='List the save files for the current session')
    async def on_cmd_listfiles(self, interaction):
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        savefiledir = os.path.join(self.savefiledir, playchan.session.autosave)
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
        playchan = get_valid_playchannel(self, interaction=interaction, withgame=True)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        if not playchan.game:
            await interaction.response.send_message('No game is being played in this channel.')
            return
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate is None:
            await interaction.response.send_message('The game is not running.')
            return
        chan = interaction.channel
        await interaction.response.send_message('Status line displayed.', ephemeral=True)
        outls = [ content_to_markup(val) for val in glkstate.statuswindat ]
        outls = rebalance_output(outls)
        for out in outls:
            if out.strip():
                await chan.send('|\n'+out)

    @appcmd('install', description='Download and install a game file for play')
    async def on_cmd_install(self, interaction, url:str):
        playchan = get_valid_playchannel(self, interaction=interaction)
        if not playchan:
            await interaction.response.send_message('Discoggin does not play games in this channel.')
            return
        
        try:
            res = await download_game_url(self, url)
        except Exception as ex:
            logging.error('Download: %s', ex, exc_info=ex)
            await interaction.response.send_message('Download error: %s' % (ex,))
        if isinstance(res, str):
            await interaction.response.send_message(res)
            return
        
        game = res
        if not isinstance(res, GameFile):
            await interaction.response.send_message('download_game_url: not a game')
            return

        session = create_session(self, game)
        set_channel_session(self, playchan, session)
        await interaction.response.send_message('Downloaded "%s" and began a new session. (**/start** to start the game.)' % (game.filename,))

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
        sessls.sort(key=lambda sess: -sess.lastupdate)
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

    @appcmd('channels', description='List channels that we can play on')
    async def on_cmd_channellist(self, interaction):
        ### good place to update the channels cache
        chanls = get_playchannels_for_server(self, interaction.guild_id, withgame=True)
        if not chanls:
            await interaction.response.send_message('Discoggin is not available on this Discord server')
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
            ### display status line?
            return
            
        game = get_game_by_name(self, gamearg)
        if not game:
            await interaction.response.send_message('Game not found: "%s"' % (gamearg,))
            return
        curgame = get_game_by_channel(self, playchan.gckey)
        if curgame and game.hash == curgame.hash:
            await interaction.response.send_message('This channel is already playing "%s".' % (curgame.filename,))
            return
            
        session = get_available_session_for_hash(self, game.hash)
        if session:
            set_channel_session(self, playchan, session)
            await interaction.response.send_message('Activated session %d for "%s"' % (session.sessid, game.filename,))
            ### display status line?
            return
        session = create_session(self, game)
        set_channel_session(self, playchan, session)
        await interaction.response.send_message('Began a new session for "%s"' % (game.filename,))
        
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
        
        cmd = extract_command(message.content)
        if not cmd:
            # silently ignore messages that don't look like commands
            return
        
        if not playchan.game:
            await message.channel.send('No game is being played in this channel.')
            return
        
        glkstate = get_glkstate_for_session(self, playchan.session)
        if glkstate is None:
            await message.channel.send('The game is not running. (**/start** to start it.)')
            return

        if playchan.sessid in self.inflight:
            logging.warning('run_turn wrapper (s%s): command in flight', playchan.sessid)
            return
        self.inflight.add(playchan.sessid)
        try:
            await self.run_turn(cmd, message.channel, playchan, glkstate)
        finally:
            self.inflight.discard(playchan.sessid)

    async def run_turn(self, cmd, chan, playchan, glkstate):
        """Execute a turn by invoking an interpreter.
        The cmd and glkstate arguments should be None for the initial turn
        (starting the game).
        We always set sessid in the inflight set before calling this,
        and clear it after this completes. This lets us avoid invoking
        two turns on the same session at the same time.
        """
        if not chan:
            logging.warning('run_turn: channel not set')
            return

        gamefile = os.path.join(self.gamesdir, playchan.game.hash, playchan.game.filename)
        if not os.path.exists(gamefile):
            logging.error('run_turn (s%s): game file not found: %s', playchan.sessid, gamefile)
            await message.channel.send('Error: The game file seems to be missing.')
            return

        if playchan.game.format == 'zcode':
            interpreter = 'bocfelr'
        elif playchan.game.format == 'glulx':
            interpreter = 'glulxer'
        else:
            logging.warning('run_turn (s%s): unknown format: %s', playchan.sessid, playchan.game.format)
            await message.channel.send('Error: No known interpreter for this format (%s)' % (playchan.game.format,))
            return
        
        autosavedir = os.path.join(self.autosavedir, playchan.session.autosave)
        if not os.path.exists(autosavedir):
            os.mkdir(autosavedir)
            
        savefiledir = os.path.join(self.savefiledir, playchan.session.autosave)
        if not os.path.exists(savefiledir):
            os.mkdir(savefiledir)

        input = None
        extrainput = None
        
        if glkstate is None:
            # Game-start case.
            if cmd is not None:
                logging.warning('run_turn (s%s): tried to send command when game was not running: %s', playchan.sessid, cmd)
                return
            
            update = {
                'type':'init', 'gen':0,
                'metrics': create_metrics(),
                'support': [ 'timer', 'hyperlinks' ],
            }
            indat = json.dumps(update)
            
            args = [ interpreter, '-singleturn', '--autosave', '--autodir', autosavedir, gamefile ]
        else:
            # Regular turn case.
            if cmd is None:
                logging.warning('run_turn (s%s): tried to send no command when game was running', playchan.sessid)
                return
                
            try:
                input = glkstate.construct_input(cmd)
                indat = json.dumps(input)
            except Exception as ex:
                await chan.send('Unable to construct input: %s' % (ex,))
                return

            if input.get('type') == 'specialresponse' and input.get('response') == 'fileref_prompt':
                extrainput = cmd
            
            args = [ interpreter, '-singleturn', '-autometrics', '--autosave', '--autorestore', '--autodir', autosavedir, gamefile ]

        # Launch the interpreter, push an input event into it, and then pull
        # an update out.
        try:
            async def func():
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=savefiledir,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
                return await proc.communicate((indat+'\n').encode())
            (outdat, errdat) = await asyncio.wait_for(func(), 5)
        except TimeoutError:
            logging.error('Interpreter error (s%s): Command timed out', playchan.sessid)
            await chan.send('Interpreter error: Command timed out.')
            return
        except Exception as ex:
            logging.error('Interpreter exception (s%s): %s', playchan.sessid, ex, exc_info=ex)
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
            logging.error('Invalid JSON output (s%s): %r', playchan.sessid, outstr)
            await chan.send('Invalid JSON output: %s' % (outstr[:160],))
            return
        except Exception as ex:
            logging.error('JSON decode exception (s%s): %s', playchan.sessid, ex, exc_info=ex)
            await chan.send('JSON decode exception: %s' % (ex,))

        # Display errorls, which contains the contents of JSON-encoded
        # error stanza(s). But don't exit just because got errors.
        for msg in errorls:
            logging.error('Interpreter error message (s%s): %s', playchan.sessid, msg)
        outls = [ 'Interpreter error: %s' % (msg,) for msg in errorls ]
        outls = rebalance_output(outls)
        for out in outls:
            if out.strip():
                await chan.send(out)

        if update is None:
            # If we didn't get any *non*-errors, that's a reason to exit.
            # But make sure we report at least one error.
            if not errorls:
                logging.error('Interpreter error (s%s): no update', playchan.sessid)
                await chan.send('Interpreter error: no update')
            return

        # Update glkstate with the output.
        if glkstate is None:
            glkstate = GlkState()
        try:
            glkstate.accept_update(update, extrainput)
        except Exception as ex:
            await chan.send('Update error: %s' % (ex,))
            return

        ### detect game-over condition and set glkstate to None!
        put_glkstate_for_session(self, playchan.session, glkstate)

        update_session_movecount(self, playchan.session)

        # Display the output.
        outls = [ content_to_markup(val) for val in glkstate.storywindat ]
        outls = rebalance_output(outls)
        for out in outls:
            if out.strip():
                await chan.send('>\n'+out)
        ### otherwise show status line? or something?
