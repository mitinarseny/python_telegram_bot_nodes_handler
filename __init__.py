import copy
import re
from typing import (Any, Callable, Dict, List, Sequence, Tuple, Union)

from telegram import (Bot, Update, TelegramObject, ChatAction, Message,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
                      InlineKeyboardButton, InlineKeyboardMarkup,
                      Audio, Contact, Document, Location, PhotoSize,
                      Sticker, Video, Voice, Venue, VideoNote, ParseMode)
from telegram.ext import (Dispatcher, Handler, RegexHandler)

TELEGRAM_OBJECT_TO_SEND = Union[str, TelegramObject]
ALLOWED_TELEGRAM_OBJECTS_WITH_CAPTION = [Audio, Document, PhotoSize, Video, Voice]
TELEGRAM_OBJECT_WITH_CAPTION_TO_SEND = Tuple[Union[Audio, Document, PhotoSize, Video, Voice], str]
TO_SEND = Union[TELEGRAM_OBJECT_TO_SEND,
                Sequence[TELEGRAM_OBJECT_TO_SEND],
                Sequence[TELEGRAM_OBJECT_WITH_CAPTION_TO_SEND]]
KEYBOARD = List[List[Union[str, KeyboardButton]]]
INLINE_KEYBOARD = List[List[InlineKeyboardButton]]


class NodesHandler(Handler):
    def __init__(self,
                 root_node: 'Node',
                 entry_handlers: List[Handler] = (),
                 back_handlers: List[Handler] = (),
                 back_str: str = None,
                 back_callback: Callable[[Bot, Update, dict], Any] = None,
                 back_pass_user_data: bool = True,
                 fallback_handlers: List[Handler] = (),
                 exit_handlers: List[Handler] = (),
                 allow_reentry: bool = False):
        self.root_node: Node = root_node
        self.entry_handlers: List[Handler] = entry_handlers
        self.back_handlers: List[Handler] = back_handlers
        self.back_str: str = back_str
        self.back_callback = back_callback or __class__.default_back_callback
        if not self.back_handlers and self.back_str:
            self.back_handlers: List[Handler] = [RegexHandler(
                pattern='^' + re.escape(self.back_str) + '$',
                callback=self.back_callback,
                pass_user_data=back_pass_user_data
            )]
        self.fallback_handlers: List[Handler] = fallback_handlers
        self.exit_handlers: List[Handler] = exit_handlers
        self.allow_reentry: bool = allow_reentry

        self.user_status_list: UserStatusList = UserStatusList()
        self.root_node.back_str = self.back_str
        self.root_node.user_status_list = self.user_status_list

    def check_update(self, update: Update):
        user_id = update.effective_user.id
        user_status = self.user_status_list[user_id]

        # check entry
        if not user_status.nodes_handler_entered or self.allow_reentry:
            for candidate in self.entry_handlers:
                if candidate.check_update(update=update):
                    user_status.current_handler = candidate
                    return True
        if user_status.nodes_handler_entered:
            # check back
            if user_status.nodes_history.current().allow_back and user_status.nodes_history.can_back():
                for candidate in self.back_handlers:
                    if candidate.check_update(update=update):
                        user_status.current_handler = candidate
                        return True
            # check exit
            for candidate in self.exit_handlers:
                if candidate.check_update(update=update):
                    user_status.current_handler = self.exit_handlers
                    return True
            # check current node
            if user_status.nodes_history.current().check_update(update=update):
                user_status.current_handler = user_status.nodes_history.current()
                return True
            # check fallback
            for candidate in self.fallback_handlers:
                if candidate.check_update(update=update):
                    user_status.current_handler = candidate
                    return True

        return False

    def handle_update(self, update: Update, dispatcher: Dispatcher):
        user_id = update.effective_user.id
        user_status = self.user_status_list[user_id]
        dispatcher.bot.send_chat_action(user_id, ChatAction.TYPING)
        handler = user_status.current_handler
        handle_result = handler.handle_update(update=update, dispatcher=dispatcher)

        if handler in self.entry_handlers or handler in self.back_handlers:
            # handle entry
            if handler in self.entry_handlers:
                user_status.enter_nodes_handler()
                user_status.display_node = self.root_node
                user_status.nodes_history.set_root(user_status.display_node)
            # handle back
            else:
                user_status.nodes_history.back()
                user_status.display_node = user_status.nodes_history.current()
                user_status.enter_current_node()
            if user_status.display_node.entry_handlers:
                user_status.display_node.entry_handlers[-1].handle_update(update=update, dispatcher=dispatcher)
            user_status.nodes_history.current().handle_entry(update=update, dispatcher=dispatcher)
        # handle exit
        elif handler in self.exit_handlers:
            user_status.exit_nodes_handler()
        return handle_result

    @staticmethod
    def default_back_callback(bot: Bot, update: Update, user_data: dict = None):
        pass

    def __repr__(self):
        return '<{cls} user_status_list: {usl}>'.format(cls=self.__class__.__name__, usl=self.user_status_list)


class UserStatusList(object):
    def __init__(self):
        self._: Dict[int, UserStatus] = {}

    def init_user(self, user_id: int):
        self._[user_id] = UserStatus()

    def user_status(self, user_id: int) -> 'UserStatus':
        return self._[user_id]

    def __len__(self):
        return len(self._)

    def __contains__(self, user_id: int):
        return user_id in self._

    def __getitem__(self, user_id: int) -> 'UserStatus':
        if user_id not in self:
            self.init_user(user_id=user_id)
        return self._[user_id]

    def __repr__(self):
        return '<{cls} len: {len}>'.format(cls=self.__class__.__name__, len=len(self))


class UserStatus(object):
    def __init__(self):
        self.nodes_handler_entered: bool = False
        self.current_handler: Handler = None
        self.current_node_handler: Handler = None
        self.nodes_history: NodesHistory = NodesHistory()
        self.display_node: Node = None
        self.is_inside_current_node: bool = False
        self.next_node: Node = None

    def enter_current_node(self):
        self.is_inside_current_node = True

    def exit_current_node(self):
        self.is_inside_current_node = False

    def enter_nodes_handler(self):
        self.nodes_handler_entered = True

    def exit_nodes_handler(self):
        self.nodes_handler_entered = False

    def __repr__(self):
        return '<{cls} entered: {entered}, current_node: {current_node}, ' \
               'display_node: {display_node}, is_inside_current_node: {is_inside_current_node}, ' \
               'current_handler: {current_handler}, nodes_history: {nodes_history}>' \
            .format(cls=self.__class__.__name__,
                    entered=self.nodes_handler_entered,
                    current_node=self.nodes_history.current(),
                    display_node=self.display_node,
                    is_inside_current_node=self.is_inside_current_node,
                    current_handler=self.current_handler,
                    nodes_history=self.nodes_history)


class NodesHistory(object):
    def __init__(self):
        self._: List[Node] = []

    def add(self, node: 'Node'):
        if self.current():
            node.back_str = self.current().back_str
        self._.append(node)

    def set_root(self, root_node: 'Node'):
        self._ = [root_node]

    def current(self) -> Union['Node', None]:
        if len(self._):
            return self._[-1]
        return None

    def can_back(self) -> bool:
        return len(self._) > 1

    def back(self) -> 'Node':
        self._.pop()
        return self._[-1]

    def __len__(self):
        return len(self._)

    def __repr__(self):
        return '<{cls} nodes_number: {nn}>'.format(cls=self.__class__.__name__, nn=len(self))


class Node(Handler):
    INSIDE_NOT_VALID = -1

    def __init__(self,
                 entry_handlers: Sequence[Handler] = (),
                 auto_entry: bool = True,
                 hello: TO_SEND = None,
                 reply_keyboard: KEYBOARD = None,
                 remove_keyboard: bool = False,
                 inline_keyboard: INLINE_KEYBOARD = None,
                 inside_handlers: Sequence[Handler] = (),
                 inside_fallbacks: Sequence[Handler] = (),
                 goodbye: TO_SEND = None,
                 parse_mode: str = ParseMode.MARKDOWN,
                 switch_on_this: bool = True,
                 allow_back: bool = True):
        self.entry_handlers: Sequence[Handler] = entry_handlers
        self.auto_entry: bool = auto_entry
        self.hello: TO_SEND = hello
        self.__reply_keyboard: KEYBOARD = None
        self.reply_keyboard = reply_keyboard
        self.remove_keyboard: bool = remove_keyboard
        self.inline_keyboard: INLINE_KEYBOARD = inline_keyboard
        self.inside_handlers: Sequence[Handler] = inside_handlers
        self.inside_fallbacks: Sequence[Handler] = inside_fallbacks
        self.goodbye: TO_SEND = goodbye
        self.parse_mode = parse_mode

        self.user_status_list: UserStatusList = None
        self.switch_on_this: bool = switch_on_this
        self.allow_back = allow_back

        self.next_node: Node = None
        self.back_str: str = None

    def next(self, next_node: 'Node'):
        self.next_node = next_node
        return self.next_node

    def check_update(self, update: Update) -> bool:
        user_id = update.effective_user.id
        if not self.user_status_list[user_id].is_inside_current_node:
            if self.check_candidates(update=update, candidates=self.entry_handlers):
                return True
        elif self.check_candidates(update=update, candidates=self.inside_handlers):
            return True
        elif self.check_candidates(update=update, candidates=self.inside_fallbacks):
            return True
        return False

    def check_candidates(self, update: Update, candidates: Sequence[Handler]) -> bool:
        user_id = update.effective_user.id
        for candidate in candidates:
            if candidate.check_update(update=update):
                self.user_status_list[user_id].current_node_handler = candidate
                return True
        return False

    def handle_update(self, update: Update, dispatcher: Dispatcher):
        user_status = self.user_status_list[update.effective_user.id]
        handler = user_status.current_node_handler
        handle_result = handler.handle_update(update=update, dispatcher=dispatcher)
        if isinstance(handle_result, Node):
            user_status.next_node = handle_result
        if handle_result == __class__.INSIDE_NOT_VALID or handler in self.inside_fallbacks:
            if user_status.display_node.entry_handlers:
                user_status.display_node.entry_handlers[0].handle_update(update=update, dispatcher=dispatcher)
            user_status.display_node.handle_entry(update=update, dispatcher=dispatcher)
        elif handler in self.entry_handlers:
            self.handle_entry(update=update, dispatcher=dispatcher)
        elif handler in self.inside_handlers:
            self.handle_inside(update=update, dispatcher=dispatcher)

        return handle_result

    def handle_entry(self, update: Update, dispatcher: Dispatcher):
        user_status = self.user_status_list[update.effective_user.id]
        user_status.enter_current_node()
        if self.hello:
            reply_markup = None
            if self.reply_keyboard:
                reply_markup = ReplyKeyboardMarkup(self.reply_keyboard, resize_keyboard=True)  # do it in __init__()
                if self.allow_back and user_status.nodes_history.can_back() and self.back_str:
                    __class__.add_keyboard_button(reply_markup.keyboard, self.back_str)
            elif self.inline_keyboard:
                reply_markup = InlineKeyboardMarkup(self.inline_keyboard)
            if self.remove_keyboard:
                reply_markup = ReplyKeyboardRemove()
            self.reply(bot=dispatcher.bot, message=update.message, to_send=self.hello, reply_markup=reply_markup)
        if not self.inside_handlers:
            self.handle_inside(update=update, dispatcher=dispatcher)

    def handle_inside(self, update: Update, dispatcher: Dispatcher):
        user_status = self.user_status_list[update.effective_user.id]
        if self.goodbye:
            self.reply(bot=dispatcher.bot, message=update.message, to_send=self.goodbye)
        user_status.exit_current_node()
        next_node = user_status.next_node or self.next_node
        if next_node:
            next_node.user_status_list = self.user_status_list
            user_status.display_node = next_node
            if user_status.display_node.switch_on_this:
                user_status.nodes_history.add(user_status.display_node)
            user_status.next_node = None
            if user_status.display_node.auto_entry:
                if self.next_node and user_status.display_node.entry_handlers:
                    user_status.display_node.entry_handlers[0].handle_update(update=update, dispatcher=dispatcher)
                user_status.display_node.handle_entry(update=update, dispatcher=dispatcher)
        else:
            if not self.switch_on_this:
                user_status.enter_current_node()
            user_status.next_node = None

    def reply(self,
              bot: Bot,
              message: Message,
              to_send: TO_SEND,
              reply_markup: Union[ReplyKeyboardMarkup, ReplyKeyboardRemove] = None):
        if not isinstance(to_send, list):
            self.reply_object(message=message, obj=to_send, reply_markup=reply_markup)
        else:
            for _ in range(len(to_send) - 1):
                self.reply_object(message=message, obj=to_send[_], silent=True)
                bot.send_chat_action(message.from_user.id, ChatAction.TYPING)
            self.reply_object(message=message, obj=to_send[-1], reply_markup=reply_markup)

    def reply_object(self,
                     message: Message,
                     obj: Union[TELEGRAM_OBJECT_TO_SEND, TELEGRAM_OBJECT_WITH_CAPTION_TO_SEND],
                     reply_markup: Union[ReplyKeyboardMarkup, ReplyKeyboardRemove] = None,
                     silent: bool = False):
        caption = None
        if isinstance(obj, list) or isinstance(obj, tuple):
            if len(obj) == 2 and obj[0].__class__ in ALLOWED_TELEGRAM_OBJECTS_WITH_CAPTION:
                caption = obj[1]
                obj = obj[0]
            else:
                raise AttributeError
        if isinstance(obj, str):
            message.reply_text(obj, reply_markup=reply_markup, parse_mode=self.parse_mode, disable_notification=silent)
        elif isinstance(obj, Audio):
            message.reply_audio(obj, caption=caption, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, Contact):
            message.reply_contact(obj, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, Document):
            message.reply_document(obj, caption=caption, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, Location):
            message.reply_location(location=obj, reply_markup=reply_markup, disable_notification=silent)
        if isinstance(obj, PhotoSize):
            message.reply_photo(obj, caption=caption, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, Sticker):
            message.reply_sticker(obj, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, Venue):
            message.reply_venue(obj, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, Video):
            message.reply_video(obj, caption=caption, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, VideoNote):
            message.reply_video_note(obj, reply_markup=reply_markup, disable_notification=silent)
        elif isinstance(obj, Voice):
            message.reply_voice(obj, caption=caption, reply_markup=reply_markup, disable_notification=silent)

    @property
    def reply_keyboard(self) -> Union[KEYBOARD, None]:
        if isinstance(self.__reply_keyboard, list):
            return copy.deepcopy(self.__reply_keyboard)
        return None

    @reply_keyboard.setter
    def reply_keyboard(self, keyboard: KEYBOARD):
        self.__reply_keyboard = keyboard

    @staticmethod
    def add_keyboard_button(keyboard: KEYBOARD, btn: Union[KeyboardButton, InlineKeyboardButton, str],
                            max_row_len: int = 2):
        if keyboard and len(keyboard[-1]) < max_row_len:
            keyboard[-1].append(btn)
        else:
            keyboard.append([btn])

    def __repr__(self):
        return '<{cls} hello: \'{hello}\'>'.format(cls=self.__class__.__name__, hello=self.hello)


class NamedNode(Node):
    def __init__(self,
                 name: str,
                 entry_callback: Callable[[Bot, Update, dict], Any] = None,
                 entry_pass_user_data: bool = False,
                 hello: TO_SEND = None,
                 reply_keyboard: KEYBOARD = None,
                 remove_keyboard: bool = False,
                 inline_keyboard: INLINE_KEYBOARD = None,
                 inside_handlers: Sequence[Handler] = (),
                 inside_fallbacks: Sequence[Handler] = (),
                 goodbye: TO_SEND = None,
                 switch_on_this: bool = True,
                 allow_back: bool = True):
        self.name: str = name
        entry_handler = RegexHandler(
            pattern='^' + re.escape(self.name) + '$',
            callback=entry_callback or __class__.default_callback,
            pass_user_data=entry_pass_user_data)
        Node.__init__(
            self,
            entry_handlers=[entry_handler],
            hello=hello,
            reply_keyboard=reply_keyboard,
            remove_keyboard=remove_keyboard,
            inline_keyboard=inline_keyboard,
            inside_handlers=inside_handlers,
            inside_fallbacks=inside_fallbacks,
            goodbye=goodbye,
            switch_on_this=switch_on_this,
            allow_back=allow_back)

    @staticmethod
    def default_callback(bot: Bot, update: Update, user_data: dict = None):
        pass

    def __repr__(self):
        return '<{cls} name: \'{name}\'>'.format(
            cls=self.__class__.__name__,
            name=self.name)


class SwitchNode(Node):
    def __init__(self,
                 entry_handlers: Sequence[Handler] = (),
                 hello: TO_SEND = None,
                 switch_nodes: Sequence[Sequence['Node']] = (),
                 keyboard_from_names: bool = True,
                 remove_keyboard: bool = False,
                 goodbye: TO_SEND = None,
                 switch_on_this: bool = True,
                 allow_back: bool = True):

        self.switch_nodes: List[Node] = []
        inside_handlers: List[Handler] = []
        if keyboard_from_names:
            keyboard: KEYBOARD = []
        else:
            keyboard = None
        for switch_nodes_row in switch_nodes:
            if isinstance(keyboard, list):
                keyboard.append([])
            for switch_node in switch_nodes_row:
                self.switch_nodes.append(switch_node)
                if isinstance(keyboard, list) and isinstance(switch_node, NamedNode):
                    keyboard[-1].append(switch_node.name)
                for handler in switch_node.entry_handlers:
                    inside_handlers.append(handler)
        Node.__init__(
            self,
            entry_handlers=entry_handlers,
            hello=hello,
            reply_keyboard=keyboard,
            remove_keyboard=remove_keyboard,
            inside_handlers=inside_handlers,
            goodbye=goodbye,
            switch_on_this=switch_on_this,
            allow_back=allow_back)

    def handle_inside(self, update: Update, dispatcher: Dispatcher):
        user_status = self.user_status_list[update.effective_user.id]
        handler = user_status.current_node_handler
        for switch_node in self.switch_nodes:
            if handler in switch_node.entry_handlers:
                user_status.next_node = switch_node
                break
        super().handle_inside(update=update, dispatcher=dispatcher)


class NamedSwitchNode(SwitchNode, NamedNode):
    def __init__(self,
                 name: str,
                 entry_callback: Callable[[Bot, Update, dict], Any] = None,
                 entry_pass_user_data: bool = False,
                 hello: TO_SEND = None,
                 switch_nodes: Sequence[Sequence['Node']] = (),
                 keyboard_from_names: bool = True,
                 remove_keyboard: bool = False,
                 goodbye: TO_SEND = None,
                 switch_on_this: bool = True,
                 allow_back: bool = True):
        NamedNode.__init__(
            self,
            name=name,
            entry_callback=entry_callback,
            entry_pass_user_data=entry_pass_user_data,
            hello=hello,
            remove_keyboard=remove_keyboard,
            goodbye=goodbye,
            switch_on_this=switch_on_this,
            allow_back=allow_back)
        SwitchNode.__init__(
            self,
            entry_handlers=self.entry_handlers,
            hello=self.hello,
            switch_nodes=switch_nodes,
            keyboard_from_names=keyboard_from_names,
            goodbye=self.goodbye,
            switch_on_this=self.switch_on_this,
            allow_back=self.allow_back)
