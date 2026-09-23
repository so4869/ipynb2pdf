# ipynb2pdf

ipynb파일을 pdf로 변경해서 어디 제출하려고 하니 nbconverter니 miktax니 nbconverter[webpdf], library 충돌 등 나를 너무 귀찮게 해서 그냥 claude code랑 같이 ipynb2pdf하나 만들었음

Jupyter Notebook(`.ipynb`) 파일을 **수식·이미지·한글**까지 그대로 살려 PDF로 변환하는 프로그램입니다.
TeX 설치가 필요 없고, 단일 실행 파일(exe)로 배포할 수 있습니다.

## 다운로드 (설치 불필요)

| OS | 파일 |
|---|---|
| Windows 10/11 (64bit) | [ipynb2pdf.exe](https://github.com/so4869/ipynb2pdf/releases/latest/download/ipynb2pdf.exe) |
| macOS (Apple Silicon) | [ipynb2pdf-macos-arm64.zip](https://github.com/so4869/ipynb2pdf/releases/latest/download/ipynb2pdf-macos-arm64.zip) |

전체 목록: [Releases](https://github.com/so4869/ipynb2pdf/releases)

- Windows: 내려받은 exe에 `.ipynb` 파일을 드래그&드롭하거나 더블클릭해서 파일을 고르면 됩니다. SmartScreen 경고가 뜨면 "추가 정보 → 실행"을 누르세요(서명되지 않은 실행 파일이라 나오는 경고입니다).
- macOS: 압축을 풀고 터미널에서 `xattr -d com.apple.quarantine ./ipynb2pdf` 를 한 번 실행한 뒤 `./ipynb2pdf 노트북.ipynb` 로 사용합니다.

## 특징

| 항목 | 지원 내용 |
|---|---|
| 수식 | `$...$`, `$$...$$`, `\(..\)`, `\[..\]`, `align`, `cases`, `pmatrix` 등 (MathJax 렌더링) |
| 한글 | 나눔고딕/나눔고딕코딩 폰트 내장 → 어떤 PC에서도 동일하게 출력 |
| 이미지 | 셀 출력 PNG/JPEG/SVG/GIF, 마크다운 이미지(첨부·로컬·원격 URL·data URI), HTML `<img>` |
| 표 | 마크다운 표, pandas DataFrame(HTML) 표 |
| 코드 | 구문 강조, 긴 줄 자동 줄바꿈, 긴 셀 페이지 분할 |
| 출력 | stdout/stderr, ANSI 색상, 진행바(`\r`), 에러 트레이스백, `text/latex`, `text/markdown` |
| 기타 | 제목/페이지 번호, 코드/출력 숨기기 옵션, 여러 파일 일괄 변환 |

## 렌더링 엔진 (자동 선택)

1. **browser** (기본) — 노트북을 자체 HTML(MathJax + 내장 폰트, 완전 오프라인)로 만든 뒤,
   PC에 이미 설치된 **Edge / Chrome / Chromium / Brave / Whale**을 headless로 실행해 PDF로 인쇄합니다.
   Jupyter 화면과 거의 동일한 품질이며 Windows 10/11에는 Edge가 기본 내장되어 있어 별도 설치가 필요 없습니다.
2. **native** — 브라우저가 전혀 없는 PC용 순수 파이썬 엔진(ReportLab + matplotlib mathtext).
   행렬·align·cases 환경까지 자체 조판합니다. 수식 모양이 MathJax보다는 단순합니다.
3. **nbconvert** — `--engine nbconvert` 지정 시 그 PC에 설치된 `jupyter nbconvert --to webpdf`를 그대로 호출합니다.

## 사용법

```
ipynb2pdf.exe                         # 파일 선택 창이 열림 (여러 파일 선택 가능)
ipynb2pdf.exe a.ipynb b.ipynb         # 같은 폴더에 a.pdf, b.pdf 생성 (exe 아이콘에 드래그&드롭도 가능)
ipynb2pdf.exe a.ipynb -o out.pdf      # 출력 경로 지정
ipynb2pdf.exe *.ipynb --outdir pdfs   # 출력 폴더 지정
ipynb2pdf.exe a.ipynb --engine native # 엔진 강제 지정 (auto|browser|native|nbconvert)
ipynb2pdf.exe a.ipynb --no-input      # 코드 숨기고 출력만
ipynb2pdf.exe a.ipynb --no-output     # 출력 숨기고 코드만
ipynb2pdf.exe a.ipynb --keep-html     # 중간 HTML 파일도 남김 (디버깅용)
ipynb2pdf.exe --help
```

브라우저 경로를 직접 지정하려면 `--browser "C:\...\msedge.exe"` 또는 환경변수 `IPYNB2PDF_BROWSER`를 사용합니다.

## 소스로 실행

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m ipynb2pdf notebook.ipynb
```

## exe 빌드 (Windows)

Windows PC에서 (Python 3.9+ 설치 필요):

```
build_win.bat
```

`dist\ipynb2pdf.exe` 하나가 생성됩니다 (약 50 MB, 폰트·MathJax·matplotlib 포함).
PyInstaller는 크로스 컴파일을 지원하지 않으므로 exe는 Windows에서 빌드해야 합니다.
Windows PC가 없다면 저장소를 GitHub에 올리면 `.github/workflows/build.yml`이 자동으로 exe를 빌드해 Artifacts에 올려 줍니다.

macOS/Linux 실행 파일: `./build_mac.sh` → `dist/ipynb2pdf`

## 테스트

```
python tests/make_sample.py     # 기능 총망라 샘플 노트북 생성 (tests/sample.ipynb)
python -m ipynb2pdf tests/sample.ipynb
python -m ipynb2pdf tests/sample.ipynb --engine native -o tests/sample_native.pdf
```

## 프로젝트 구조

```
ipynb2pdf/
  cli.py           명령행/GUI 진입점, 엔진 선택
  html_engine.py   ipynb → HTML(MathJax, 폰트 내장) → 브라우저 인쇄
  browser.py       Chrome/Edge 탐색 및 headless 인쇄
  native_engine.py ipynb → ReportLab PDF (순수 파이썬)
  mathimg.py       LaTeX → PNG (matplotlib mathtext + 행렬/align 자체 조판)
  mdmath.py        마크다운에서 수식 추출/보호
  notebook.py      노트북 로드, 이미지 경로 해석
  ansi.py          ANSI 색상 처리
  htmlutil.py      HTML 표/텍스트 추출
resources/
  fonts/           NanumGothic, NanumGothicCoding (OFL)
  mathjax/         tex-svg-full.js (Apache 2.0)
  style.css        인쇄용 스타일
  mpl_fontlist.json  matplotlib 폰트 캐시(첫 실행 지연 방지)
ipynb2pdf.spec     PyInstaller 설정
```

## 라이선스 고지

- 나눔글꼴: SIL Open Font License 1.1 (© NAVER)
- MathJax: Apache License 2.0
