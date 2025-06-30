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

At present, Discoggin can only play:

- Z-code games (file suffix `.z1` through `.z8` plus `.zblorb`) 
- Glulx games (file suffix `.ulx` and `.gblorb`)
- Ink games (file suffix `.json` or `.js`) (you want the `ink.json` file)

It does not support extended display features like graphics or sound. (So `.z6` is not actually going to work.)

`UNDO` does not work in Z-code games.

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
- **/recap** _COUNT_ : Recap the last few commands (max of 10).
- **/files** : List save files (and other data files) recorded in this session.
- **/forcequit** : Shut down a game if it's gotten stuck for some reason. (You will then need to **/start** it again.)

Sessions are referred to by number. Games are referred to by filename, or part of the filename. (**/select scroll** will suffice to find `Scroll_Thief.gblorb`, if it's installed.)

## Under the hood

Discoggin uses traditional IF interpreters installed on the bot server. When a player enters a command, the bot fires up the interpreter, loads the last-saved position, passes in the command, saves the position again, and reports the command results on the Discord channel.

The interpreters use an autosave feature, so you never have to explicitly save a game. But if you do, the save file is kept as part of the session data. The same is true of transcripts or other game data files.

Because the interpreter only runs a single move at a time, there is no RAM or CPU cost associated with a session -- whether the session is active or background. Nothing is cached in memory; it's all files on disk. On the down side, the server incurs the CPU cost of launching an interpreter every time a command is processed.

Getting even deeper: the interpreters all use the [RemGlk][] library, which translates the standard IF interface (story and status windows) into a stream of JSON updates. The Discoggin bot therefore just has to launch the interpreter as a subprocess (with the `--singleturn` option), and pass JSON in and out.

[RemGlk]: https://github.com/erkyrath/remglk

## Setting up Discoggin

To run your own installation of Discoggin, you must create a Discord application.

## On Discord's web site

Go to the [Discord developer portal][discorddev] and hit "New Application".

[discorddev]: https://discord.com/developers/applications

On the General Information tab, give your bot an appropriate name. For this example, we will call it "MyDiscoggin".

On the Installation tab, turn *off* the "User Install" checkbox. Then, under "Guild Install", add "bot" to the Scopes line. A new line will appear for Permissions; add "Manage Channels", "Manage Messages", "Send Messages", "Use Slash Commands".

On the Bot tab, turn *on* the "Message Content Intent" switch. Hit the "Reset Token" button to create a bot token; record its value.

Back on the Installation tab, use the URL under "Install Link" to install the application on your Discord instance. Give it the permissions it asks for.

The MyDiscoggin bot will appear on your server, but it will appear as offline. That's because the bot process isn't running yet.

Create a channel for Discoggin to play games in. For the sake of example, we will call it `#game`.

### On your machine

Set up a directory to hold the bot's files. Create subdirectories:

	mkdir sql games terps autosaves savefiles log

Copy the [`sample.config`](./sample.config) file into your directory and rename it `app.config`.

In `app.config`, change the `BotToken` entry to the token value you recorded above. (If you didn't write down the value, you'll have to reset it again -- Discord only shows you the token once.)

Create a venv for the application. (The [discord.py][] library doesn't play well with some other modules, so I prefer to use a venv.)

	python3 -m venv venv
	./venv/bin/pip3 install -r requirements.txt

Make sure the `discoggin` module is in your `$PYTHON_PATH` (or in the venv).

Compile [Glulxe][] and [Bocfel][] with the [RemGlk][] library. I'm afraid I don't have detailed instructions for this. It's a pain in the butt. Once you've figured it out, put the `glulxe` and `bocfel` binaries in the `terps` directory.

[Glulxe]: https://github.com/erkyrath/glulxe
[Bocfel]: https://github.com/erkyrath/bocfel

Install [inkrun.js][] in the `terps` directory.

[inkrun.js]: https://github.com/erkyrath/inkrun-single

Create the bot's SQLite database:

	./venv/bin/python3 -m discoggin createdb

Activate the bot in your `#game` channel. Use this command, replacing the URL with the channel URL from your Discord server:

	./venv/bin/python3 -m discoggin addchannel https://discord.com/channels/12345678/87654321

Install the bot's slash commands on your server:

	./venv/bin/python3 -m discoggin --logstream cmdinstall

Hit slash in your Discord window to see a list of the commands. You may have to reload your Discord window to make them appear. The commands won't work yet, though, because the bot isn't running.

Time to do that! This command will start the bot:

	./venv/bin/python3 -m discoggin

Log output will be written to `log/bot.log` (or wherever you configured it in `app.config`). If you want to log to stdout, use the `--logstream` option:

	./venv/bin/python3 -m discoggin --logstream

