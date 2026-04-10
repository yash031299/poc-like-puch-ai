"""TokenRingBuffer — async circular buffer for LLM tokens → TTS streaming."""

import asyncio
from collections import deque
from typing import Optional


class TokenRingBuffer:
    """
    Fixed-capacity circular buffer for coordinating LLM token production with TTS consumption.
    
    LLM producer puts tokens; TTS consumer gets tokens.
    Implements backpressure: LLM waits if buffer is full.
    
    Attributes:
        capacity: Max tokens before backpressure (default 256)
    """

    def __init__(self, capacity: int = 256):
        """Initialize ring buffer with fixed capacity."""
        if capacity <= 0:
            raise ValueError(f"Capacity must be > 0, got {capacity}")
        self._capacity = capacity
        self._buffer: deque[str] = deque()
        self._complete = False
        self._lock = asyncio.Lock()
        self._put_event = asyncio.Event()  # Signals: "space available for put"
        self._get_event = asyncio.Event()  # Signals: "token available for get"
        self._put_event.set()  # Buffer initially has space

    async def put(self, token: str) -> None:
        """
        Put a single token into the buffer.
        
        Waits (backpressure) if buffer is full.
        Signals consumers that a token is available.
        
        Args:
            token: LLM token to add
            
        Raises:
            ValueError: If complete() was already called
        """
        if not token:
            raise ValueError("Token cannot be empty")

        while True:
            async with self._lock:
                if self._complete:
                    raise ValueError("Cannot put token after complete() called")

                # If buffer has space, add token and return
                if len(self._buffer) < self._capacity:
                    self._buffer.append(token)
                    self._get_event.set()  # Signal: token available
                    return
                
                # Buffer is full, prepare to wait
                self._put_event.clear()
            
            # Wait outside the lock
            await self._put_event.wait()

    async def get(self) -> Optional[str]:
        """
        Get next token from buffer.
        
        Waits if buffer is empty (unless complete() was called).
        Returns None if buffer is empty and complete() was called (EOF).
        
        Returns:
            Next token, or None if EOF and buffer exhausted
        """
        while True:
            async with self._lock:
                # If buffer has tokens, return one
                if len(self._buffer) > 0:
                    token = self._buffer.popleft()
                    self._put_event.set()  # Signal: space available for put
                    return token
                
                # If complete, return None (EOF)
                if self._complete:
                    return None
                
                # Buffer empty and not complete, prepare to wait
                self._get_event.clear()
            
            # Wait outside the lock
            await self._get_event.wait()

    async def complete(self) -> None:
        """
        Signal that no more tokens will be added (EOF).
        
        Wakes up any waiting consumers.
        """
        async with self._lock:
            self._complete = True
            self._get_event.set()  # Wake up waiting consumers

    def is_complete(self) -> bool:
        """Check if complete() has been called."""
        return self._complete

    def is_empty(self) -> bool:
        """Check if buffer is currently empty."""
        return len(self._buffer) == 0

    def size(self) -> int:
        """Current number of tokens in buffer."""
        return len(self._buffer)

    def capacity(self) -> int:
        """Capacity of the buffer."""
        return self._capacity
