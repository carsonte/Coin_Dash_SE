from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SilentModeState:
    low_count: int = 0
    resume_count: int = 0
    silent: bool = False


class SilentModeController:
    def __init__(self, low_threshold: int, resume_threshold: int) -> None:
        self.low_threshold = low_threshold
        self.resume_threshold = resume_threshold
        self.state = SilentModeState()

    def register(self, active: bool) -> SilentModeState:
        st = self.state
        if active:
            st.low_count = 0
            st.resume_count += 1
            if st.silent and st.resume_count >= self.resume_threshold:
                st.silent = False
        else:
            st.resume_count = 0
            st.low_count += 1
            if st.low_count >= self.low_threshold:
                st.silent = True
        self.state = st
        return st

    def reset(self) -> None:
        self.state = SilentModeState()
