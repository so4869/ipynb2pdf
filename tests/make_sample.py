"""Generate a feature-rich sample notebook for testing ipynb2pdf."""
import base64, io, json, os, sys
import nbformat
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell, new_output, new_raw_cell

HERE = os.path.dirname(os.path.abspath(__file__))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# --- images
x = np.linspace(0, 2 * np.pi, 200)
fig, ax = plt.subplots(figsize=(6, 3.2))
ax.plot(x, np.sin(x), label="sin"); ax.plot(x, np.cos(x), label="cos"); ax.legend(); ax.set_title("sin / cos")
buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=110); png_b64 = base64.b64encode(buf.getvalue()).decode()
buf = io.BytesIO(); fig.savefig(buf, format="svg"); svg_text = buf.getvalue().decode()
plt.close(fig)
fig, ax = plt.subplots(figsize=(4, 4)); ax.imshow(np.random.RandomState(0).rand(20, 20), cmap="viridis"); ax.set_title("heatmap")
fig.savefig(os.path.join(HERE, "local_image.png"), dpi=80); plt.close(fig)
fig, ax = plt.subplots(figsize=(3, 2)); ax.bar(["a", "b", "c"], [3, 5, 2]); buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=90)
att_b64 = base64.b64encode(buf.getvalue()).decode(); plt.close(fig)
# tall image
fig, ax = plt.subplots(figsize=(4, 14)); ax.plot(np.random.RandomState(1).randn(300).cumsum()); ax.set_title("tall figure")
buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=100); tall_b64 = base64.b64encode(buf.getvalue()).decode(); plt.close(fig)

df_html = """<div>
<style scoped>.dataframe tbody tr th:only-of-type { vertical-align: middle; } .dataframe thead th { text-align: right; }</style>
<table border="1" class="dataframe">
  <thead><tr style="text-align: right;"><th></th><th>이름</th><th>나이</th><th>점수</th><th>비고</th></tr></thead>
  <tbody>
    <tr><th>0</th><td>김철수</td><td>23</td><td>88.5</td><td>우수</td></tr>
    <tr><th>1</th><td>이영희</td><td>31</td><td>92.0</td><td>최우수</td></tr>
    <tr><th>2</th><td>Park &amp; Co.</td><td>45</td><td>NaN</td><td>None</td></tr>
  </tbody>
</table>
</div>"""

md1 = r"""# ipynb2pdf 테스트 노트북

이 노트북은 **한글**, *수식*, `코드`, 이미지, 표 등이 모두 잘 변환되는지 확인하기 위한 것입니다.
영어 텍스트 mixed with 한국어 텍스트, 그리고 긴 문장이 자동으로 줄바꿈되는지도 확인합니다. 아주아주아주아주아주아주아주아주아주아주아주아주아주아주아주아주아주아주아주아주 긴 문장.

## 인라인 수식

질량-에너지 등가식 $E = mc^2$ 과 오일러 공식 $e^{i\pi} + 1 = 0$, 그리고 분수 $\frac{a+b}{c}$ 와 적분 $\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}$ 이 문장 속에 있습니다.
달러 기호는 $5 and $6 처럼 쓰이면 수식이 아닙니다. 그리고 \(x_1 + x_2\) 형태도 지원합니다.

## 디스플레이 수식

$$
\hat{\boldsymbol{\theta}} = \underset{\theta}{\arg\max} \; \sum_{i=1}^{N} \log p(x_i \mid \theta)
$$

\[ \nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}, \qquad \nabla \times \mathbf{B} - \frac{1}{c^2}\frac{\partial \mathbf{E}}{\partial t} = \mu_0 \mathbf{J} \]

정렬 환경:

\begin{align}
f(x) &= (x+a)(x+b) \\
     &= x^2 + (a+b)x + ab \tag{1}
\end{align}

행렬과 케이스:

$$
\mathbf{A} = \begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}, \quad
\mathbf{B} = \begin{bmatrix} \alpha & \beta \\ \gamma & \delta \end{bmatrix}, \quad
|x| = \begin{cases} x & \text{if } x \ge 0 \\ -x & \text{otherwise} \end{cases}
$$

$$\lim_{n\to\infty} \left(1 + \frac{1}{n}\right)^n = e, \qquad \sum_{k=0}^{\infty} \frac{x^k}{k!} = e^x, \qquad \mathbb{E}[X] = \int x\,f(x)\,dx$$

$$ \text{한글 텍스트 } \mathcal{L}(\theta) = -\frac{1}{N}\sum_i y_i \log \hat{y}_i \implies \theta^* $$

## 목록, 인용, 표

1. 첫 번째 항목
2. 두 번째 항목 with $\alpha_i$
   - 중첩 항목 **굵게**
   - 중첩 항목 *기울임* ~~취소선~~
3. 세 번째

- [x] 완료된 작업
- [ ] 미완료 작업

> 인용문입니다. "수식 $a^2+b^2=c^2$ 도 인용문 안에서 렌더링됩니다."
> — 피타고라스

| 항목 | 값 | 설명 |
|:-----|---:|:----:|
| 학습률 | 0.001 | $\eta$ |
| 배치 크기 | 64 | 미니배치 |
| 에폭 | 100 | 반복 횟수 |

링크: [Jupyter](https://jupyter.org) 와 인라인 코드 `print("안녕")`, 그리고 코드 블록:

```python
def 인사(name: str) -> str:
    return f"안녕하세요, {name}님!"   # 주석
```

---

### 이미지

첨부 이미지: ![attached](attachment:bar.png)

로컬 파일 이미지: ![local](local_image.png)

HTML 이미지 태그: <img src="local_image.png" width="200"/>

<b>raw HTML bold</b>, <span style="color:red">빨간 글씨</span>, 줄바꿈<br>다음 줄
"""

nb = new_notebook()
nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nb.metadata["language_info"] = {"name": "python"}
cells = []
c = new_markdown_cell(md1); c["attachments"] = {"bar.png": {"image/png": att_b64}}; cells.append(c)

c = new_code_cell("import numpy as np\nimport matplotlib.pyplot as plt\n\n# 한글 주석\ndef f(x):\n    \"\"\"문서 문자열\"\"\"\n    return np.sin(x) ** 2\n\nprint('안녕하세요', f(1.0))\nfor i in range(3):\n    print(i, end=' ')", execution_count=1)
c.outputs = [new_output("stream", name="stdout", text="안녕하세요 0.7080734182735712\n0 1 2 ")]
cells.append(c)

c = new_code_cell("x = np.linspace(0, 2*np.pi, 200)\nplt.plot(x, np.sin(x)); plt.plot(x, np.cos(x))\nplt.show()", execution_count=2)
c.outputs = [new_output("display_data", data={"image/png": png_b64, "text/plain": "<Figure size 600x320 with 1 Axes>"})]
cells.append(c)

c = new_code_cell("import pandas as pd\ndf = pd.DataFrame({'이름': ['김철수','이영희','Park & Co.'], '나이':[23,31,45], '점수':[88.5,92.0,None]})\ndf", execution_count=3)
c.outputs = [new_output("execute_result", data={"text/html": df_html, "text/plain": "        이름  나이    점수\n0  김철수  23  88.5\n1  이영희  31  92.0\n2  Park & Co.  45   NaN"}, execution_count=3)]
cells.append(c)

c = new_code_cell("from IPython.display import SVG, Latex, Markdown, display\ndisplay(SVG(svg_text))\nLatex(r'$\\displaystyle \\int_a^b f(x)\\,dx = F(b) - F(a)$')", execution_count=4)
c.outputs = [new_output("display_data", data={"image/svg+xml": svg_text, "text/plain": "<IPython.core.display.SVG object>"}),
             new_output("execute_result", data={"text/latex": "$\\displaystyle \\int_a^b f(x)\\,dx = F(b) - F(a)$", "text/plain": "<IPython.core.display.Latex object>"}, execution_count=4)]
cells.append(c)

c = new_code_cell("import sympy as sp\nx = sp.symbols('x')\nsp.Integral(sp.exp(-x**2), (x, -sp.oo, sp.oo))", execution_count=5)
c.outputs = [new_output("execute_result", data={"text/latex": "$\\displaystyle \\int\\limits_{-\\infty}^{\\infty} e^{- x^{2}}\\, dx$", "text/plain": "Integral(exp(-x**2), (x, -oo, oo))"}, execution_count=5)]
cells.append(c)

c = new_code_cell("display(Markdown('### 마크다운 출력\\n- 항목 $x^2$\\n- **굵게**'))", execution_count=6)
c.outputs = [new_output("display_data", data={"text/markdown": "### 마크다운 출력\n- 항목 $x^2$\n- **굵게**", "text/plain": "<IPython.core.display.Markdown object>"})]
cells.append(c)

c = new_code_cell("from tqdm import tqdm\nfor i in tqdm(range(3)): pass\nimport sys; print('경고!', file=sys.stderr)", execution_count=7)
c.outputs = [new_output("stream", name="stderr", text="\r  0%|          | 0/3 [00:00<?, ?it/s]\r100%|██████████| 3/3 [00:00<00:00, 3000.00it/s]\n경고!\n"),
             new_output("stream", name="stdout", text="\x1b[1m\x1b[31m빨간 굵게\x1b[0m 일반 \x1b[32m초록\x1b[0m \x1b[38;5;208m주황\x1b[0m \x1b[4m밑줄\x1b[0m\n")]
cells.append(c)

c = new_code_cell("def divide(a, b):\n    return a / b\n\ndivide(1, 0)", execution_count=8)
c.outputs = [new_output("error", ename="ZeroDivisionError", evalue="division by zero", traceback=[
    "\x1b[0;31m---------------------------------------------------------------------------\x1b[0m",
    "\x1b[0;31mZeroDivisionError\x1b[0m                         Traceback (most recent call last)",
    "Cell \x1b[0;32mIn[8], line 4\x1b[0m\n\x1b[1;32m      1\x1b[0m \x1b[38;5;28;01mdef\x1b[39;00m \x1b[38;5;21mdivide\x1b[39m(a, b):\n\x1b[1;32m      2\x1b[0m     \x1b[38;5;28;01mreturn\x1b[39;00m a \x1b[38;5;241m/\x1b[39m b\n\x1b[0;32m----> 4\x1b[0m \x1b[43mdivide\x1b[49m\x1b[43m(\x1b[49m\x1b[38;5;241;43m1\x1b[39;49m\x1b[43m,\x1b[49m\x1b[43m \x1b[49m\x1b[38;5;241;43m0\x1b[39;49m\x1b[43m)\x1b[49m",
    "Cell \x1b[0;32mIn[8], line 2\x1b[0m, in \x1b[0;36mdivide\x1b[0;34m(a, b)\x1b[0m\n\x1b[1;32m      1\x1b[0m \x1b[38;5;28;01mdef\x1b[39;00m \x1b[38;5;21mdivide\x1b[39m(a, b):\n\x1b[0;32m----> 2\x1b[0m     \x1b[38;5;28;01mreturn\x1b[39;00m \x1b[43ma\x1b[49m\x1b[43m \x1b[49m\x1b[38;5;241;43m/\x1b[39;49m\x1b[43m \x1b[49m\x1b[43mb\x1b[49m",
    "\x1b[0;31mZeroDivisionError\x1b[0m: division by zero"])]
cells.append(c)

long_code = "\n".join("value_%03d = compute_something_quite_long(argument_one=%d, argument_two='문자열 %d', argument_three=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])" % (i, i, i) for i in range(60))
c = new_code_cell(long_code, execution_count=9)
c.outputs = [new_output("stream", name="stdout", text="\n".join("line %d: %s" % (i, "가나다라마바사 " * 5) for i in range(80)))]
cells.append(c)

c = new_code_cell("plt.figure(figsize=(4, 14)); plt.plot(np.random.randn(300).cumsum())", execution_count=10)
c.outputs = [new_output("display_data", data={"image/png": tall_b64, "text/plain": "<Figure>"})]
cells.append(c)

c = new_code_cell("# 출력이 없는 셀\nresult = 42")
cells.append(c)

cells.append(new_raw_cell("이것은 raw 셀입니다.\n  들여쓰기 유지"))

cells.append(new_markdown_cell(r"""## 더 많은 수식

$\sqrt[3]{x}$, $\binom{n}{k}$, $\overline{AB}$, $\vec{v} \cdot \hat{n}$, $\|x\|_2 \le \|x\|_1$, $x \in \mathbb{R}^{n\times m}$, $\partial_t u = \Delta u$, $\lVert w \rVert$, $\mathcal{N}(\mu, \sigma^2)$, $\therefore$, $\ge$, $\to$, $\iff$

$$ \frac{\partial \mathcal{L}}{\partial w} = \frac{1}{m}\sum_{i=1}^{m} \left( \sigma(w^\top x^{(i)} + b) - y^{(i)} \right) x^{(i)} $$

$$ P(A \mid B) = \frac{P(B \mid A)\,P(A)}{P(B)} $$

$$\begin{aligned} \mathrm{softmax}(z)_i &= \frac{e^{z_i}}{\sum_j e^{z_j}} \\ \text{CE}(y, \hat y) &= -\sum_i y_i \log \hat y_i \end{aligned}$$

$$ \det \begin{vmatrix} a & b & c \\ d & e & f \\ g & h & i \end{vmatrix} = aei + bfh + cdg - ceg - bdi - afh $$

원격 이미지: ![remote](https://raw.githubusercontent.com/jupyter/notebook/main/docs/source/_static/images/notebook-running-code.png)
"""))

nb.cells = cells
out = os.path.join(HERE, "sample.ipynb")
nbformat.write(nb, out)
print("wrote", out)
