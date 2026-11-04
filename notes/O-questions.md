# O 단계: PDF 그림과 확장자 없는 그림 — 결정과 확인 필요

## 문제
pdflatex 원고는 그림을 PDF 로 넣고 확장자를 생략하는 일이 많다 (`\includegraphics{fig}` → fig.pdf).
브라우저 엔진은 `<img>` 로 PDF 를 그리지 못하고, 뷰어는 확장자 없는 주소를 그림으로 찾지 않았다.

## 정한 것
- **뷰어**: PDF 그림은 QtPdf(PySide6 에 들어 있음, pdfium)로 첫 쪽을 2배 해상도 PNG 로 그리고, 원래 쪽 크기
  (pt → CSS px, ×96/72)를 지닌 SVG 로 감싸 `<img>` 에 내준다. 고유 크기가 맞으니 `width=` 없는 그림도 원고와 같은 크기,
  화면은 또렷하다. 투명 배경은 흰색으로 (어두운 테마에서도 그림이 읽히게). 내용 해시로 32개 LRU.
- **확장자 없는 그림**: LaTeX 처럼 찾는다. 순서는 `.svg → .png → .jpg → .jpeg → .gif → .webp → .pdf`
  (pdflatex 는 .pdf 를 먼저 찾지만, 웹 형식이 있으면 그것이 더 가볍고 정확하다).
- **구별**: 렌더러의 새 훅 `image_url` 로 뷰어가 PDF·확장자 없는 그림 주소에 `?htex-image=1` 을 붙인다.
  표시가 있을 때만 그림으로 응답하고, 같은 `.pdf` 를 링크로 열면 예전과 같다 (문서로 다룸).
  원격 `https://…/f.pdf` 그림도 표시를 붙여 뷰어(htex:)를 거치게 한다. Content-Type 이 application/pdf 면 PDF 로 본다.
- **정적 빌드 (`htex build`)**: Qt 가 없다. 확장자 없는 그림과 PDF 그림은 같은 이름의 웹 형식 파일
  (fig.svg·fig.png …)이 있으면 그 이름으로 바꿔 쓰고, 없으면 경고만 (주소는 그대로).
- **EPS**: 지원하지 않는다. `missing-resource` 경고 ("PDF·SVG·PNG 로 바꿔 주세요"). 진단 코드는 새로 만들지 않았다.
- **묶음**: `QtPdf` 를 EXCLUDE_QT 에서 뺐다 (QtPdfWidgets·PdfQuick 은 여전히 뺌). 크기 증가는 libQt6Pdf 몇 MB.
  `check_bundle.py` 가 Qt Pdf 라이브러리 존재를, 스모크 테스트가 `packaging/smoke/pdf-figure.tex` 의 두 그림
  (확장자 있음·없음)이 실제로 그려지는지 본다.

## 확인 필요
- 여러 쪽 PDF 그림의 `page=` 선택지 (`\includegraphics[page=2]{…}`): 지금은 첫 쪽만.
- `htex serve` 는 정적 빌드와 달리 아직 대체 그림을 찾지 않는다.
- 아주 큰 PDF 쪽(포스터 등)은 긴 변 3000px 로 줄여 그린다.
