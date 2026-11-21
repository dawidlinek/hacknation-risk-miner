# Załącznik: licencje bibliotek backendu (Python)

Wygenerowano poleceniem `cd backend && uv run --with pip-licenses pip-licenses --format=markdown --with-urls` (pip-licenses nie jest dodany do `pyproject.toml`), 2026-11-21, środowisko `backend/.venv` (zależności produkcyjne i grupa `dev`).

Kolumna „Zakres”: `runtime` = obraz produkcyjny (`uv sync --no-dev`), `dev` = tylko testy i narzędzia programistyczne (grupa `dev` i ich zależności przechodnie). Przypisanie wynika z `uv export --no-dev --frozen` (64 pakiety runtime); pozycje oznaczone `dev` nie trafiają do obrazu produkcyjnego.

| Pakiet | Wersja | Licencja | Zakres | URL |
|---|---|---|---|---|
| Mako | 1.4.3 | MIT | runtime | https://www.makotemplates.org/ |
| MarkupSafe | 3.0.4 | BSD-3-Clause | runtime | https://github.com/pallets/markupsafe/ |
| PyYAML | 6.0.4 | MIT License | runtime | https://pyyaml.org/ |
| Pygments | 2.21.0 | BSD-2-Clause | dev | https://pygments.org |
| RapidFuzz | 3.14.6 | MIT | runtime | https://github.com/rapidfuzz/RapidFuzz |
| SQLAlchemy | 2.1.9 | MIT | runtime | https://www.sqlalchemy.org |
| Werkzeug | 3.1.9 | BSD-3-Clause | dev | https://github.com/pallets/werkzeug/ |
| alembic | 1.20.1 | MIT | runtime | https://alembic.sqlalchemy.org |
| annotated-doc | 0.0.7 | MIT | runtime | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.8.0 | MIT | runtime | https://github.com/annotated-types/annotated-types |
| anyio | 4.16.0 | MIT | runtime | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| asyncpg | 0.32.0 | Apache-2.0 | runtime | UNKNOWN |
| certifi | 2026.11.20 | Mozilla Public License 2.0 (MPL 2.0) | runtime | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | runtime | https://cffi.readthedocs.io/en/latest/whatsnew.html |
| charset-normalizer | 3.5.2 | MIT | runtime | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| click | 8.5.1 | BSD-3-Clause | runtime | https://github.com/pallets/click/ |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | runtime | https://github.com/pyca/cryptography |
| distro | 1.9.0 | Apache Software License | runtime | https://github.com/python-distro/distro |
| et_xmlfile | 2.0.0 | MIT License | runtime | https://foss.heptapod.net/openpyxl/et_xmlfile |
| fastapi | 0.165.0 | MIT | runtime | https://github.com/fastapi/fastapi |
| google-auth | 2.63.0 | Apache Software License | runtime | https://github.com/googleapis/google-cloud-python/tree/main/packages/google-auth |
| google-genai | 3.6.1 | Apache-2.0 | runtime | https://github.com/googleapis/python-genai |
| graphql-core | 3.3.2 | MIT | dev | https://github.com/graphql-python/graphql-core |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | runtime | https://greenlet.readthedocs.io |
| h11 | 0.16.0 | MIT License | runtime | https://github.com/python-hyper/h11 |
| harfile | 0.7.0 | MIT | dev | https://github.com/schemathesis/harfile/blob/main/CHANGELOG.md |
| httpcore | 1.0.9 | BSD-3-Clause | runtime | https://www.encode.io/httpcore/ |
| httpcore2 | 2.16.2 | BSD-3-Clause | runtime | https://github.com/pydantic/httpx2 |
| httptools | 0.9.0 | MIT | runtime | https://github.com/MagicStack/httptools |
| httpx | 0.28.1 | BSD License | runtime | https://github.com/encode/httpx |
| httpx2 | 2.16.2 | BSD-3-Clause | runtime | https://github.com/pydantic/httpx2 |
| hypothesis | 6.170.17 | MPL-2.0 | dev | https://hypothesis.works |
| hypothesis-graphql | 0.13.7 | MIT | dev | https://github.com/Stranger6667/hypothesis-graphql/blob/master/CHANGELOG.md |
| idna | 3.20 | BSD-3-Clause | runtime | https://github.com/kjd/idna |
| iniconfig | 2.3.1 | MIT | dev | https://github.com/pytest-dev/iniconfig |
| itsdangerous | 2.2.0 | BSD License | runtime | https://github.com/pallets/itsdangerous/ |
| jiter | 0.19.0 | MIT | runtime | https://github.com/pydantic/jiter/ |
| jsonschema_rs | 0.61.2 | MIT License | dev | https://github.com/Stranger6667/jsonschema/tree/master/crates/jsonschema-py |
| lxml | 6.1.3 | BSD-3-Clause | runtime | https://lxml.de/ |
| markdown-it-py | 4.3.0 | MIT License | dev | https://github.com/executablebooks/markdown-it-py |
| mdurl | 0.1.2 | MIT License | dev | https://github.com/executablebooks/mdurl |
| numpy | 2.5.5 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | runtime | https://numpy.org |
| openai | 3.57.0 | Apache-2.0 | runtime | https://github.com/openai/openai-python |
| openpyxl | 3.1.5 | MIT License | runtime | https://openpyxl.readthedocs.io |
| opentelemetry-api | 1.45.2 | Apache-2.0 | runtime | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| orjson | 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | runtime | https://github.com/ijl/orjson |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | dev | https://github.com/pypa/packaging |
| pgvector | 0.5.1 | MIT | runtime | https://github.com/pgvector/pgvector-python |
| pluggy | 1.7.0 | MIT License | dev | https://github.com/pytest-dev/pluggy |
| pyasn1 | 0.6.5 | BSD-2-Clause | runtime | https://github.com/pyasn1/pyasn1 |
| pyasn1_modules | 0.4.2 | BSD License | runtime | https://github.com/pyasn1/pyasn1-modules |
| pycparser | 3.12 | BSD-3-Clause | runtime | https://github.com/eliben/pycparser |
| pydantic | 2.14.4 | MIT | runtime | https://github.com/pydantic/pydantic |
| pydantic-settings | 2.16.3 | MIT | runtime | https://github.com/pydantic/pydantic-settings |
| pydantic_core | 2.50.5 | MIT | runtime | https://github.com/pydantic |
| pypdfium2 | 5.15.2 | BSD-3-Clause, Apache-2.0, dependency licenses | runtime | https://github.com/pypdfium2-team/pypdfium2 |
| pyrate-limiter | 4.5.1 | MIT | dev | https://github.com/vutran1710/PyrateLimiter |
| pytest | 9.2.0 | MIT | dev | https://docs.pytest.org/en/latest/ |
| pytest-asyncio | 1.5.0 | Apache-2.0 | dev | https://github.com/pytest-dev/pytest-asyncio |
| python-dateutil | 4.0.0 | BSD-3-Clause | runtime | https://github.com/dateutil/dateutil |
| python-docx | 1.2.0 | MIT License | runtime | https://github.com/python-openxml/python-docx |
| python-dotenv | 1.2.4 | BSD-3-Clause | runtime | https://github.com/theskumar/python-dotenv |
| python-multipart | 0.0.34 | Apache-2.0 | runtime | https://github.com/Kludex/python-multipart |
| requests | 2.34.2 | Apache Software License | runtime | https://github.com/psf/requests |
| rich | 15.0.0 | MIT License | dev | https://github.com/Textualize/rich |
| riskminer | 0.1.0 | MIT | runtime | UNKNOWN |
| ruff | 0.17.6 | MIT | dev | https://docs.astral.sh/ruff |
| schemathesis | 4.33.4 | MIT | dev | https://github.com/schemathesis/schemathesis/blob/master/CHANGELOG.md |
| selectolax | 1.0.2 | MIT | runtime | https://github.com/rushter/selectolax |
| sniffio | 1.3.1 | Apache Software License; MIT License | runtime | https://github.com/python-trio/sniffio |
| sortedcontainers | 2.4.0 | Apache Software License | dev | http://www.grantjenks.com/docs/sortedcontainers/ |
| sqlglot | 30.33.0 | MIT | runtime | https://sqlglot.com/ |
| starlette | 1.10.0 | BSD-3-Clause | runtime | https://github.com/Kludex/starlette |
| tenacity | 9.1.4 | Apache Software License | runtime | https://github.com/jd/tenacity |
| truststore | 0.10.5 | MIT | runtime | https://github.com/sethmlarson/truststore |
| typing-inspection | 0.4.5 | MIT | runtime | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | runtime | https://github.com/python/typing_extensions |
| tzdata | 2026.6 | Apache-2.0 | runtime | https://github.com/python/tzdata |
| urllib3 | 2.8.0 | MIT | runtime | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| uvicorn | 0.54.0 | BSD-3-Clause | runtime | https://uvicorn.dev/ |
| uvloop | 0.23.0 | Apache Software License; MIT License | runtime | UNKNOWN |
| watchfiles | 1.3.0 | MIT License | runtime | https://github.com/samuelcolvin/watchfiles |
| websockets | 17.4 | BSD-3-Clause | runtime | https://github.com/python-websockets/websockets |

Uwagi:

- `riskminer` (MIT) to sam projekt.
- `certifi` (MPL-2.0) i część `orjson` (MPL-2.0 AND (Apache-2.0 OR MIT)): MPL-2.0 to licencja słabego copyleftu na poziomie pliku, używana bez modyfikacji jako biblioteka; zgodna z zasadą „MPL jako narzędzie” w projekcie.
- `hypothesis` (MPL-2.0): tylko testy (zależność `schemathesis`), nie trafia do obrazu produkcyjnego.
- `pypdfium2`: BSD-3-Clause i Apache-2.0 (PDFium: BSD-3-Clause/Apache-2.0).
- Brak pakietów GPL, LGPL, AGPL, SSPL ani CC-BY-NC.
