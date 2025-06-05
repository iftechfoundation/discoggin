# Discoggin -- a Discord bot for playing parser IF games

- Copyright 2025 by Andrew Plotkin <erkyrath@eblong.com>
- Distributed under the MIT license
- Implemented with the [discord.py][] library

[discord.py]: https://github.com/Rapptz/discord.py/

Discoggin (the name doesn't mean anything) allows players to run old-style interactive fiction games in a Discord channel. You play by typing commands like `>GET LAMP` as regular Discord chat messages. The initial `>` indicates a game command. The bot will carry out the command and respond with the game's output.

Discoggin is configured to run on specific Discord channels, which are assumed to be dedicated to playing IF. (Non-players can mute the those channels.) It can only play one game at a time per channel, but it can keep any number of game sessions paused in the background. A "session" is a particular game along with its current state and any save files you've created.

(The idea is that one group of players might log in on Tuesdays to play game X, while another group is playing game Y on Thursdays. You just have to **/select** your game session when you arrive in the channel. You will be back in your game, exactly where you left off.)

(Yes, you can have two sessions playing the same game. In case the Tuesday and Thursday crowds have similar tastes. Each session is its own "save slot".)

Sessions and games not played for thirty days will be discarded.

## Limitations

There are many. Discoggin is a work in progress.

At present, Discoggin can only play Z-code games (file suffix `.z1` through `.z8` plus `.zblorb`) and Glulx games (file suffix `.ulx` and `.gblorb`). It does not support extended display features like graphics, sound, or hyperlinks. (So `.z6` is not actually going to work.)

`UNDO` is currently not working.

The status line is broken on Z-code games. (Gets stuck on the first turn or blank.)

There is currently no way to download save files. Similarly, you can create a transcript, but there is no way to view it.

## Slash commands

Discoggin is controlled with the usual sort of Discord slash commands.

- **/install** _URL_ : Download and install a game for play.
- **/games** : List games available for play.
- **/channels** : List channels available to play on.
- **/sessions** : List game sessions in progress.
- **/select** _GAME_ : Select a game to play in this channel. (This looks for an existing session of that game, or starts a new session.)
- **/select** _SESSION_ : Select an existing session.
- **/newsession** _GAME_ : Explicitly start a new session for the named game.
- **/start** : Begin the selected game in this channel.
- **/status** : Display the current status line of a game.
- **/files** : List save files (and other data files) recorded in this session.
- **/forcequit** : Shut down a game if it's gotten stuck for some reason. (You will then need to **/start** it again.)

Sessions are referred to by number. Games are referred to by filename, or part of the filename. (**/select scroll** will suffice to find `Scroll_Thief.gblorb`, if it's installed.)

## Under the hood

Discoggin uses traditional IF interpreters installed on the bot server. When a player enters a command, the bot fires up the interpreter, loads the last-saved position, passes in the command, saves the position again, and reports the command results on the Discord channel.

The interpreters use an autosave feature, so you never have to explicitly save a game. But if you do, the save file is kept as part of the session data. The same is true of transcripts or other game data files.

Because the interpreter only runs a single move at a time, there is no RAM or CPU cost associated with a session -- whether the session is active or background. Nothing is cached in memory; it's all files on disk. On the down side, the server incurs the CPU cost of launching an interpreter every time a command is processed.

Getting even deeper: the interpreters all use the [RemGlk][] library, which translates the standard IF interface (story and status windows) into a stream of JSON updates. The Discoggin bot therefore just has to launch the interpreter as a subprocess (with the `--singleturn` option), and pass JSON in and out.

[RemGlk]: https://github.com/erkyrath/remglk

