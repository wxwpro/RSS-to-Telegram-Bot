import asyncio
import re
from time import sleep
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telethon import TelegramClient, events
from telethon.errors import ApiIdPublishedFloodError
from telethon.tl.custom import Message, Button
from telethon.tl import types
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.bots import SetBotCommandsRequest
from re import compile as re_compile
from typing import Optional, Union
from datetime import datetime
from functools import wraps, partial
from random import sample
from pathlib import Path

from src import env, log
from src.parsing import tgraph
from src.feed import Feed, Feeds
from src.parsing.post import Post

# log
logger = log.getLogger('RSStT')

# global var placeholder
feeds: Optional[Feeds] = None
conflictCount = 0

# permission verification
ANONYMOUS_ADMIN = 1087968824

# parser
commandParser = re_compile(r'\s')

# initializing bot
Path("config").mkdir(parents=True, exist_ok=True)
bot = None
if not env.API_ID or not env.API_HASH:
    _use_sample_api = True
    logger.info('API_ID and/or API_HASH not set, use sample APIs instead. API_ID_PUBLISHED_FLOOD_ERROR may occur.')
    API_IDs = sample(tuple(env.SAMPLE_APIS.keys()), len(env.SAMPLE_APIS))
    sleep_for = 0
    while API_IDs:
        sleep_for += 10
        API_ID = API_IDs.pop()
        API_HASH = env.SAMPLE_APIS[API_ID]
        try:
            bot = TelegramClient('config/bot', API_ID, API_HASH, proxy=env.TELEGRAM_PROXY_DICT, request_retries=3) \
                .start(bot_token=env.TOKEN)
            break
        except ApiIdPublishedFloodError:
            logger.warning(f'API_ID_PUBLISHED_FLOOD_ERROR occurred. Sleep for {sleep_for}s and retry.')
            sleep(sleep_for)

else:
    _use_sample_api = False
    bot = TelegramClient('config/bot', env.API_ID, env.API_HASH, proxy=env.TELEGRAM_PROXY_DICT, request_retries=3) \
        .start(bot_token=env.TOKEN)

if bot is None:
    logger.critical('LOGIN FAILED!')
    exit(1)

env.bot = bot
bot_peer: types.InputPeerUser = asyncio.get_event_loop().run_until_complete(bot.get_me(input_peer=True))
env.bot_id = bot_peer.user_id


def permission_required(func=None, *, only_manager=False, only_in_private_chat=False):
    if func is None:
        return partial(permission_required, only_manager=only_manager,
                       only_in_private_chat=only_in_private_chat)

    @wraps(func)
    async def wrapper(event: Union[events.NewMessage.Event, Message], *args, **kwargs):
        command = event.text if event.text else '(no command, file message)'
        sender_id = event.sender_id
        sender: Optional[types.User] = await event.get_sender()
        sender_fullname = sender.first_name + (f' {sender.last_name}' if sender.last_name else '')

        if only_manager and sender_id != env.MANAGER:
            await event.respond('????????????????????????????????????????????????\n'
                                'This command can be only used by the bot manager.')
            logger.info(f'Refused {sender_fullname} ({sender_id}) to use {command}.')
            return

        if event.is_private:
            logger.info(f'Allowed {sender_fullname} ({sender_id}) to use {command}.')
            return await func(event, *args, **kwargs)

        if event.is_group:
            chat: types.Chat = await event.get_chat()
            input_chat: types.InputChannel = await event.get_input_chat()  # supergroup is a special form of channel
            if only_in_private_chat:
                await event.respond('???????????????????????????????????????\n'
                                    'This command can not be used in a group.')
                logger.info(f'Refused {sender_fullname} ({sender_id}) to use {command} in '
                            f'{chat.title} ({chat.id}).')
                return

            input_sender = await event.get_input_sender()

            if sender_id != ANONYMOUS_ADMIN:
                participant: types.channels.ChannelParticipant = await bot(
                    GetParticipantRequest(input_chat, input_sender))
                is_admin = (isinstance(participant.participant, types.ChannelParticipantAdmin)
                            or isinstance(participant.participant, types.ChannelParticipantCreator))
                participant_type = type(participant.participant).__name__
            else:
                is_admin = True
                participant_type = 'AnonymousAdmin'

            if not is_admin:
                await event.respond('???????????????????????????????????????\n'
                                    'This command can be only used by an administrator.')
                logger.info(
                    f'Refused {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                    f'in {chat.title} ({chat.id}).')
                return
            logger.info(
                f'Allowed {sender_fullname} ({sender_id}, {participant_type}) to use {command} '
                f'in {chat.title} ({chat.id}).')
            return await func(event, *args, **kwargs)
        return

    return wrapper


@bot.on(events.NewMessage(pattern='/list'))
@permission_required(only_manager=True)
async def cmd_list(event: Union[events.NewMessage.Event, Message]):
    list_result = '<br>'.join(f'<a href="{feed.link}">{feed.name}</a>' for feed in feeds)
    if not list_result:
        await event.respond('???????????????')
        return
    result_post = Post('<b><u>????????????</u></b><br><br>' + list_result, plain=True, service_msg=True)
    await result_post.send_message(event.chat_id, event.id if not event.is_private else None)


@bot.on(events.NewMessage(pattern='/add'))
@permission_required(only_manager=True)
async def cmd_add(event: Union[events.NewMessage.Event, Message]):
    args = commandParser.split(event.text)
    if len(args) < 3:
        await event.respond('ERROR: ???????????????: /add ?????? RSS')
        return
    title = args[1]
    url = args[2]
    if await feeds.add_feed(name=title, link=url, uid=event.chat_id):
        await event.respond('????????? \n??????: %s\nRSS ???: %s' % (title, url))


@bot.on(events.NewMessage(pattern='/remove'))
@permission_required(only_manager=True)
async def cmd_remove(event: Union[events.NewMessage.Event, Message]):
    args = commandParser.split(event.text)
    if len(args) < 2:
        await event.respond("ERROR: ??????????????????")
        return
    name = args[1]
    if feeds.del_feed(name):
        await event.respond("?????????: " + name)
        return
    await event.respond("ERROR: ???????????????????????????: " + name)


@bot.on(events.NewMessage(pattern='/help|/start'))
@permission_required(only_manager=True)
async def cmd_help(event: Union[events.NewMessage.Event, Message]):
    await event.respond(
        "<a href='https://github.com/Rongronggg9/RSS-to-Telegram-Bot'>"
        "RSS to Telegram bot???????????????????????????????????? RSS Bot???</a>\n\n"
        f"?????????????????? RSS ??????, ??????????????????????????????????????? {env.DELAY} ???????????? (?????????)\n\n"
        "???????????????????????? RSS ??????????????????????????????????????????????????????\n\n"
        "??????:\n"
        "<u><b>/add</b></u> <u><b>??????</b></u> <u><b>RSS</b></u> : ????????????\n"
        "<u><b>/remove</b></u> <u><b>??????</b></u> : ????????????\n"
        "<u><b>/list</b></u> : ?????????????????????????????????\n"
        "<u><b>/test</b></u> <u><b>RSS</b></u> <u><b>????????????(??????)</b></u> <u><b>????????????(??????)</b></u> : "
        "??? RSS ?????????????????? post (????????? 0-based, ?????????????????????????????? 0?????????????????????????????????????????? post)???"
        "??????????????? <code>all</code> ????????????\n"
        "<u><b>/import</b></u> : ????????????\n"
        "<u><b>/export</b></u> : ????????????\n"
        "<u><b>/version</b></u> : ????????????\n"
        "<u><b>/help</b></u> : ??????????????????\n\n"
        f"?????? chatid ???: {event.chat_id}",
        parse_mode='html'
    )


@bot.on(events.NewMessage(pattern='/test'))
@permission_required(only_manager=True)
async def cmd_test(event: Union[events.NewMessage.Event, Message]):
    args = commandParser.split(event.text)
    if len(args) < 2:
        await event.respond('ERROR: ???????????????: /test RSS ??????????????????(??????) ??????????????????(??????)')
        return
    url = args[1]

    if len(args) > 2 and args[2] == 'all':
        start = 0
        end = None
    elif len(args) == 3:
        start = int(args[2])
        end = int(args[2]) + 1
    elif len(args) == 4:
        start = int(args[2])
        end = int(args[3]) + 1
    else:
        start = 0
        end = 1

    try:
        await Feed(link=url).send(event.chat_id, start, end, web_semaphore=False)
    except Exception as e:
        logger.warning(f"Sending failed:", exc_info=e)
        await event.respond('ERROR: ????????????')
        return


@bot.on(events.NewMessage(pattern='/import'))
@permission_required(only_manager=True)
async def cmd_import(event: Union[events.NewMessage.Event, Message]):
    await event.respond('???????????????????????? OPML ??????',
                        buttons=Button.force_reply())
    # single_use=False, selective=Ture, placeholder='???????????????????????? OPML ??????'


@bot.on(events.NewMessage(pattern='/export'))
@permission_required(only_manager=True)
async def cmd_export(event: Union[events.NewMessage.Event, Message]):
    opml_file = feeds.export_opml()
    if opml_file is None:
        await event.respond('???????????????')
        return
    await event.respond(file=opml_file,
                        attributes=(types.DocumentAttributeFilename(
                            f"RSStT_export_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.opml"),))


class NewFileMessage(events.NewMessage):
    def __init__(self, chats=None, *, blacklist_chats=False, func=None, incoming=None, outgoing=None, from_users=None,
                 forwards=None, pattern=None, filename_pattern: str = None):
        self.filename_pattern = re.compile(filename_pattern).match
        super().__init__(chats, blacklist_chats=blacklist_chats, func=func, incoming=incoming, outgoing=outgoing,
                         from_users=from_users, forwards=forwards, pattern=pattern)

    def filter(self, event):
        document: types.Document = event.message.document
        if not document:
            return
        if self.filename_pattern:
            filename = None
            for attr in document.attributes:
                if isinstance(attr, types.DocumentAttributeFilename):
                    filename = attr.file_name
                    break
            if not self.filename_pattern(filename or ''):
                return
        return super().filter(event)


@bot.on(NewFileMessage(filename_pattern=r'^.*\.opml$'))
@permission_required(only_manager=True)
async def opml_import(event: Union[events.NewMessage.Event, Message]):
    reply_message: Message = await event.get_reply_message()
    if not event.is_private and reply_message.sender_id != env.bot_id:
        return
    try:
        opml_file = await event.download_media(file=bytes)
    except Exception as e:
        await event.reply('ERROR: ??????????????????')
        logger.warning(f'Failed to get opml file: ', exc_info=e)
        return
    await event.reply('???????????????...\n'
                      '?????????????????????????????????????????????????????????????????????????????????????????????')
    logger.info(f'Got an opml file.')
    res = await feeds.import_opml(opml_file)
    if res is None:
        await event.reply('ERROR: ?????????????????????????????????')
        return

    valid = res['valid']
    invalid = res['invalid']
    import_result = '<b><u>????????????</u></b><br><br>' \
                    + ('???????????????<br>' if valid else '') \
                    + '<br>'.join(f'<a href="{feed["link"]}">{feed["name"]}</a>' for feed in valid) \
                    + ('<br><br>' if valid and invalid else '') \
                    + ('???????????????<br>' if invalid else '') \
                    + '<br>'.join(f'<a href="{feed["link"]}">{feed["name"]}</a>' for feed in invalid)
    result_post = Post(import_result, plain=True, service_msg=True)
    await result_post.send_message(event.chat_id, event.message.id)


@bot.on(events.NewMessage(pattern='/version'))
@permission_required(only_manager=True)
async def cmd_version(event: Union[events.NewMessage.Event, Message]):
    await event.respond(env.VERSION)


async def rss_monitor(fetch_all: bool = False):
    await feeds.monitor(fetch_all)


def main():
    global feeds
    logger.info(f"RSS-to-Telegram-Bot ({', '.join(env.VERSION.split())}) started!\n"
                f"CHATID: {env.CHATID}\n"
                f"MANAGER: {env.MANAGER}\n"
                f"DELAY: {env.DELAY}s\n"
                f"T_PROXY (for Telegram): {env.TELEGRAM_PROXY if env.TELEGRAM_PROXY else 'not set'}\n"
                f"R_PROXY (for RSS): {env.REQUESTS_PROXIES['all'] if env.REQUESTS_PROXIES else 'not set'}\n"
                f"DATABASE: {'Redis' if env.REDIS_HOST else 'Sqlite'}\n"
                f"TELEGRAPH: {f'Enable ({tgraph.apis.count} accounts)' if tgraph.apis else 'Disable'}")

    commands = [types.BotCommand(command="add", description="????????????"),
                types.BotCommand(command="remove", description="????????????"),
                types.BotCommand(command="list", description="??????????????????"),
                types.BotCommand(command="test", description="??????"),
                types.BotCommand(command="import", description="????????????"),
                types.BotCommand(command="export", description="????????????"),
                types.BotCommand(command="version", description="????????????"),
                types.BotCommand(command="help", description="????????????")]
    try:
        asyncio.get_event_loop().run_until_complete(
            bot(SetBotCommandsRequest(scope=types.BotCommandScopeDefault(), lang_code='', commands=commands)))
    except Exception as e:
        logger.warning('Set command error: ', exc_info=e)

    feeds = Feeds()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(rss_monitor, trigger='cron', minute='*/1', max_instances=5, timezone='utc')
    scheduler.start()

    bot.run_until_disconnected()


if __name__ == '__main__':
    main()
