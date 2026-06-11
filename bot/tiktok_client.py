import asyncio
import logging
from typing import Callable, Awaitable

from TikTokLive import TikTokLiveClient
from TikTokLive.events import (
    ConnectEvent,
    DisconnectEvent,
    CommentEvent,
    FollowEvent,
    GiftEvent,
)

logger = logging.getLogger(__name__)


class TikTokChatClient:
    def __init__(self, username: str):
        self._username = username
        self._client: TikTokLiveClient | None = None
        self._on_comment: Callable[[str, str], Awaitable[None]] | None = None
        self._on_connect: Callable[[], Awaitable[None]] | None = None
        self._on_disconnect: Callable[[], Awaitable[None]] | None = None
        self._on_follow: Callable[[str, str], Awaitable[None]] | None = None
        # (display_name, uid, gift_name, count, diamonds, group_id)
        self._on_gift: (
            Callable[[str, str, str, int, int, int], Awaitable[None]] | None
        ) = None

    def set_callbacks(
        self,
        on_comment: Callable[[str, str], Awaitable[None]],
        on_connect: Callable[[], Awaitable[None]] | None = None,
        on_disconnect: Callable[[], Awaitable[None]] | None = None,
        on_follow: Callable[[str, str], Awaitable[None]] | None = None,
        on_gift: (
            Callable[[str, str, str, int, int, int], Awaitable[None]] | None
        ) = None,
    ):
        self._on_comment = on_comment
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_follow = on_follow
        self._on_gift = on_gift

    async def start(self):
        self._client = TikTokLiveClient(unique_id=self._username)

        @self._client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            logger.info("Connected to TikTok live: @%s", self._username)
            if self._on_connect:
                await self._on_connect()

        @self._client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            logger.info("Disconnected from TikTok live: @%s", self._username)
            if self._on_disconnect:
                await self._on_disconnect()

        @self._client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            username = event.user.nickname or event.user.unique_id
            comment = event.comment
            logger.debug("Chat message from %s: %s", username, comment)
            if self._on_comment:
                await self._on_comment(username, comment)

        @self._client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            # nickname is the display name shown in chat; unique_id is the
            # stable @handle used for dedup (nicknames can collide/change).
            display = event.user.nickname or event.user.unique_id
            uid = event.user.unique_id or display
            logger.debug("New follower: %s (@%s)", display, uid)
            if self._on_follow:
                await self._on_follow(display, uid)

        @self._client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            # Streakable gifts (combos) re-fire on every tick while the streak
            # is live; only the FINAL event has streaking=False and carries the
            # full repeat_count. Non-streakable gifts always have
            # streaking=False, so this single check collapses both cases to one
            # thank-you with the correct total — never one per combo tick.
            if event.streaking:
                return
            display = event.user.nickname or event.user.unique_id
            uid = event.user.unique_id or display
            gift_name = event.gift.name or "un regalo"
            count = event.repeat_count or 1
            diamonds = (event.gift.diamond_count or 0) * count
            group_id = event.group_id or 0
            logger.debug(
                "Gift from %s: %s x%d (%d diamonds)",
                display, gift_name, count, diamonds,
            )
            if self._on_gift:
                await self._on_gift(
                    display, uid, gift_name, count, diamonds, group_id
                )

        # start() connects and returns the heartbeat Task (it does NOT block).
        # Await that task so this call blocks until the stream actually ends
        # (disconnect, error, or stop()). Returning None here would make the
        # caller's `await` fall through and tear the bot down right after connect.
        task = await self._client.start()
        await task

    async def stop(self):
        if self._client:
            await self._client.disconnect()
            self._client = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.connected
