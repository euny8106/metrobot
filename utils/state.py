from dataclasses import dataclass, field
from typing import Optional

@dataclass
class MetronomeState:
    interval: float          # 초 단위 간격
    max_num: int             # 최대 번호
    excluded: set = field(default_factory=set)   # 제외된 번호들
    is_running: bool = False
    current_num: int = 1     # 현재 읽고 있는 번호 추적용

    def get_active_numbers(self) -> list[int]:
        """현재 활성화된 번호 리스트 반환"""
        return [n for n in range(1, self.max_num + 1) if n not in self.excluded]

    def next_numbers_from(self, start: int) -> list[int]:
        """start부터 끝까지 활성 번호 반환 (현재 라운드 나머지)"""
        return [n for n in range(start, self.max_num + 1) if n not in self.excluded]

    def exclude(self, num: int):
        if 1 <= num <= self.max_num:
            self.excluded.add(num)

    def include(self, num: int):
        """번호 복귀 - 범위 밖이면 max_num 확장"""
        if num > self.max_num:
            self.max_num = num
        self.excluded.discard(num)

    def reset_excluded(self):
        self.excluded.clear()

    def summary(self) -> str:
        excluded_str = ", ".join(str(n) for n in sorted(self.excluded)) if self.excluded else "없음"
        return f"⏱️ {self.interval}s  |  범위: 1~{self.max_num}  |  제외: {excluded_str}"
