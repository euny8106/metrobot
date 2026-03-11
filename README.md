# 🎵 MetroBot - Discord 메트로놈 봇

레이드/파티 플레이에서 클레릭 캐스팅 타이밍을 맞춰주는 Discord 음성 메트로놈 봇입니다.

---

## ⚡ 빠른 시작

### 1. 환경 세팅
```bash
pip install -r requirements.txt
```

FFmpeg 설치 필요:
- **Windows**: https://ffmpeg.org/download.html → PATH 등록
- **Mac**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### 2. Discord 봇 토큰 발급
1. https://discord.com/developers/applications 접속
2. New Application → Bot → Token 복사
3. Bot 권한 설정:
   - `Send Messages`
   - `Connect` (음성)
   - `Speak` (음성)
   - `Use Slash Commands`
4. `.env.example` → `.env` 복사 후 토큰 입력

### 3. 서버 초대 URL 생성
Developer Portal → OAuth2 → URL Generator
- Scopes: `bot`, `applications.commands`
- Permissions: `Send Messages`, `Connect`, `Speak`

### 4. 실행
```bash
python bot.py
```

---

## 🎮 명령어

| 명령어 | 설명 |
|--------|------|
| `/met` | 모달 UI로 메트로놈 설정 |
| `/met 3 10` | 3초 간격, 1~10 새로 시작 |
| `/stop` | 메트로놈 중단 + 채널 퇴장 |
| `/status` | 상태 확인 + 버튼 UI로 조작 |

---

## 📁 프로젝트 구조

```
metrobot/
├── bot.py              # 봇 엔트리포인트
├── cogs/
│   └── metronome.py    # 메트로놈 명령어 & 루프
├── utils/
│   ├── state.py        # 메트로놈 상태 관리
│   ├── audio.py        # TTS 오디오 생성/캐싱
│   └── ui.py           # Discord 버튼 UI
├── audio/              # 생성된 mp3 캐시 (자동 생성)
├── requirements.txt
├── railway.toml
└── nixpacks.toml
```
