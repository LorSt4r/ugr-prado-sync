"""
Global pytest fixtures and mock environments for PradoOS E2E and integration tests.

Provides:
- Isolated temporary directories for configuration (~/.config/prado) and courses root.
- In-memory mock keyring fixture to isolate tests from host OS credential store.
- Comprehensive Moodle / PRADO UGR HTML and JSON response fixtures.
- Mock HTTP transport and server adapter simulating the full SimpleSAMLphp SSO,
  3-tier MFA challenge, AJAX course auto-discovery, HTML activity parsing, and
  chunked streaming downloads.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from requests.adapters import HTTPAdapter
from requests.models import Response
from requests.structures import CaseInsensitiveDict

# Ensure src/ is importable
import sys
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# -----------------------------------------------------------------------------
# 1. Authoritative Mock HTML & JSON Fixtures
# -----------------------------------------------------------------------------

SAML_IDP_LOGIN_HTML = """<!DOCTYPE html>
<html lang="es">
<head><title>Universidad de Granada - SimpleSAMLphp IdP</title></head>
<body>
  <div id="content">
    <h2>Identificación de Usuarios de la UGR</h2>
    <form action="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass" method="post" name="f">
      <input type="hidden" name="AuthState" value="_authState_valid_token_12345" />
      <label for="username">Usuario:</label>
      <input type="text" id="username" name="username" value="" />
      <label for="password">Contraseña:</label>
      <input type="password" id="password" name="password" />
      <input type="submit" name="submit" value="Iniciar sesión" />
    </form>
  </div>
</body>
</html>
"""

SAML_IDP_RETRY_HTML = """<!DOCTYPE html>
<html>
<head><title>Sesión Caducada</title></head>
<body>
  <div class="error">
    <p>Su sesión ha caducado o el enlace ya no es válido.</p>
    <form action="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass" method="get">
      <input type="hidden" name="retryURL" value="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass?AuthState=_authState_refreshed_99999" />
      <input type="submit" value="Reintentar inicio de sesión" />
    </form>
  </div>
</body>
</html>
"""

SAML_IDP_INVALID_CREDS_HTML = """<!DOCTYPE html>
<html>
<head><title>Error de Identificación</title></head>
<body>
  <div class="error">
    <p class="error">Usuario o contraseña incorrectos. Por favor, inténtelo de nuevo.</p>
    <form action="https://idp.ugr.es/simplesaml/module.php/core/loginuserpass" method="post">
      <input type="hidden" name="AuthState" value="_authState_invalid_attempt" />
      <input type="text" name="username" />
      <input type="password" name="password" />
    </form>
  </div>
</body>
</html>
"""

SAML_IDP_LOCKED_HTML = """<!DOCTYPE html>
<html>
<head><title>Cuenta Bloqueada</title></head>
<body>
  <div class="error">
    <p class="error">Su cuenta ha sido bloqueada temporalmente por demasiados intentos erróneos.</p>
  </div>
</body>
</html>
"""

SAML_ASSERTION_POST_HTML = """<!DOCTYPE html>
<html>
<head><title>SAML Auto-Submit</title></head>
<body onload="document.forms[0].submit()">
  <form method="post" action="https://pradogrado2627.ugr.es/auth/saml2/sp/saml2-acs.php/pradogrado2627.ugr.es">
    <input type="hidden" name="SAMLResponse" value="PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz48c2FtbDJwOlJlc3BvbnNlIHhtbG5zOnNhbWwycD0idXJuOm9hc2lzOm5hbWVzOnRjOlNBTUw6Mi4wOnByb3RvY29sIiBJRD0iX21vY2tfYXNzZXJ0aW9uIj48L3NhbWwycDpSZXNwb25zZT4=" />
    <input type="hidden" name="RelayState" value="https://pradogrado2627.ugr.es/auth/saml2/login.php" />
    <noscript><input type="submit" value="Continuar" /></noscript>
  </form>
</body>
</html>
"""

MFA_CHALLENGE_HTML = """<!DOCTYPE html>
<html lang="es">
<head><title>PRADO UGR - Verificación en dos pasos</title></head>
<body class="path-admin-tool-mfa">
  <div class="card">
    <h3>Verificación en dos pasos (MFA)</h3>
    <p>Se ha enviado un código de verificación de 6 dígitos a su correo electrónico institucional.</p>
    <form method="post" action="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php" id="mfa_form">
      <input type="hidden" name="sesskey" value="test_sesskey_mfa_123" />
      <input type="hidden" name="_qf__tool_mfa_local_form_login_form" value="1" />
      <input type="hidden" name="factor" value="email" />
      <label for="verificationcode">Código de verificación:</label>
      <input type="text" name="verificationcode" id="verificationcode" maxlength="6" autocomplete="one-time-code" />
      <label>
        <input type="checkbox" name="factor_token_trust" value="1" checked="checked" />
        No volver a pedir el código en este equipo durante 30 días
      </label>
      <input type="submit" name="submitbutton" value="Continuar" />
    </form>
  </div>
</body>
</html>
"""

MFA_ERROR_HTML = """<!DOCTYPE html>
<html>
<head><title>MFA Error</title></head>
<body>
  <div class="alert alert-danger">
    El código de verificación introducido no es válido o ha caducado.
  </div>
  <form method="post" action="https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php">
    <input type="hidden" name="sesskey" value="test_sesskey_mfa_123" />
    <input type="text" name="verificationcode" />
    <input type="checkbox" name="factor_token_trust" value="1" />
  </form>
</body>
</html>
"""

MOODLE_MY_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <title>Área personal | PRADO UGR</title>
  <script>var M = {cfg: {sesskey: "sesskey_authed_user_999", wwwroot: "https://pradogrado2627.ugr.es"}};</script>
</head>
<body class="path-my">
  <div class="usermenu">
    <span class="userbutton"><span class="avatars"><img src="/pix/u/f1.png" alt="" /></span></span>
    <a href="https://pradogrado2627.ugr.es/login/logout.php?sesskey=sesskey_authed_user_999">Cerrar sesión</a>
  </div>
  <div id="page-content">
    <h1>Área personal</h1>
    <div class="block_myoverview" data-region="myoverview">
      <div class="course-info-container">
        <a href="https://pradogrado2627.ugr.es/course/view.php?id=15819" class="coursename">
          ESTRUCTURA DE DATOS - 2627 (Grupo C)
        </a>
      </div>
      <div class="course-info-container">
        <a href="https://pradogrado2627.ugr.es/course/view.php?id=15820" class="coursename">
          SISTEMAS OPERATIVOS - 2627 (Grupo E)
        </a>
      </div>
      <div class="course-info-container">
        <a href="https://pradogrado2627.ugr.es/course/view.php?id=15821" class="coursename">
          MODELOS DE COMPUTACIÓN - 2627 (Grupo B)
        </a>
      </div>
      <div class="course-info-container">
        <a href="https://pradogrado2627.ugr.es/course/view.php?id=15822" class="coursename">
          TEORÍA DE LA INFORMACIÓN Y CODIFICACIÓN - 2627 (Grupo A)
        </a>
      </div>
      <div class="course-info-container">
        <a href="https://pradogrado2627.ugr.es/course/view.php?id=15823" class="coursename">
          VISIÓN POR COMPUTADOR - 2627 (Grupo A)
        </a>
      </div>
    </div>
  </div>
</body>
</html>
"""

MOODLE_AJAX_COURSES_DATA = [
    {
        "id": 15819,
        "fullname": "ESTRUCTURA DE DATOS - 2627 (Grupo C)",
        "shortname": "ESTRUCTURA DE DATOS (2627)-296_11_22_2627_C",
        "idnumber": "296_11_22_2627_C",
        "startdate": 1788739200,
        "enddate": 1820275200,
        "visible": True,
        "viewurl": "https://pradogrado2627.ugr.es/course/view.php?id=15819",
        "coursecategory": "Grado en Ingeniería Informática",
        "isfavourite": False,
        "hidden": False,
    },
    {
        "id": 15820,
        "fullname": "SISTEMAS OPERATIVOS - 2627 (Grupo E)",
        "shortname": "SISTEMAS OPERATIVOS (2627)-296_11_23_2627_E",
        "idnumber": "296_11_23_2627_E",
        "startdate": 1788739200,
        "enddate": 1820275200,
        "visible": True,
        "viewurl": "https://pradogrado2627.ugr.es/course/view.php?id=15820",
        "coursecategory": "Grado en Ingeniería Informática",
        "isfavourite": False,
        "hidden": False,
    },
    {
        "id": 15821,
        "fullname": "MODELOS DE COMPUTACIÓN - 2627 (Grupo B)",
        "shortname": "MODELOS DE COMPUTACIÓN (2627)-296_11_31_2627_B",
        "idnumber": "296_11_31_2627_B",
        "startdate": 1788739200,
        "enddate": 1820275200,
        "visible": True,
        "viewurl": "https://pradogrado2627.ugr.es/course/view.php?id=15821",
        "coursecategory": "Grado en Ingeniería Informática",
        "isfavourite": False,
        "hidden": False,
    },
    {
        "id": 15822,
        "fullname": "TEORÍA DE LA INFORMACIÓN Y CODIFICACIÓN - 2627 (Grupo A)",
        "shortname": "TEORÍA DE LA INFORMACIÓN (2627)-296_11_AA_2627_A",
        "idnumber": "296_11_AA_2627_A",
        "startdate": 1788739200,
        "enddate": 1820275200,
        "visible": True,
        "viewurl": "https://pradogrado2627.ugr.es/course/view.php?id=15822",
        "coursecategory": "Grado en Ingeniería Informática",
        "isfavourite": False,
        "hidden": False,
    },
    {
        "id": 15823,
        "fullname": "VISIÓN POR COMPUTADOR - 2627 (Grupo A)",
        "shortname": "VISIÓN POR COMPUTADOR (2627)-296_11_4B_2627_A",
        "idnumber": "296_11_4B_2627_A",
        "startdate": 1788739200,
        "enddate": 1820275200,
        "visible": True,
        "viewurl": "https://pradogrado2627.ugr.es/course/view.php?id=15823",
        "coursecategory": "Grado en Ingeniería Informática",
        "isfavourite": False,
        "hidden": False,
    },
]

MOODLE_COURSE_15819_HTML = """<!DOCTYPE html>
<html lang="es">
<head><title>ESTRUCTURA DE DATOS - 2627 (Grupo C)</title></head>
<body class="course-15819">
  <div class="course-content">
    <ul class="topics">
      <!-- Section 0: General -->
      <li class="section main clearfix" id="section-0">
        <h3 class="sectionname">General</h3>
        <ul class="section img-text">
          <li class="activity modtype_forum" id="module-107901">
            <div class="activityinstance">
              <a href="https://pradogrado2627.ugr.es/mod/forum/view.php?id=107901">
                <span class="instancename">Avisos y Novedades del Curso Foro</span>
              </a>
            </div>
          </li>
          <li class="activity modtype_url" id="module-107902">
            <div class="activityinstance">
              <a href="https://pradogrado2627.ugr.es/mod/url/view.php?id=107902">
                <span class="instancename">Guía Docente Oficial URL</span>
              </a>
            </div>
          </li>
        </ul>
      </li>

      <!-- Section 1: Tema 1 -->
      <li class="section main clearfix" id="section-1">
        <h3 class="sectionname">Tema 1: Eficiencia de Algoritmos</h3>
        <ul class="section img-text">
          <li class="activity modtype_resource" id="module-107913">
            <div class="activityinstance">
              <a href="https://pradogrado2627.ugr.es/mod/resource/view.php?id=107913">
                <span class="instancename">Tema 1 - Diapositivas de Eficiencia Archivo</span>
              </a>
            </div>
          </li>
        </ul>
      </li>

      <!-- Section 2: Tema 2 -->
      <li class="section main clearfix" id="section-2">
        <h3 class="sectionname">Tema 2: Árboles y Estructuras Jerárquicas</h3>
        <ul class="section img-text">
          <li class="activity modtype_folder" id="module-107914">
            <div class="activityinstance">
              <a href="https://pradogrado2627.ugr.es/mod/folder/view.php?id=107914">
                <span class="instancename">Material Adicional Árboles AVL Carpeta</span>
              </a>
            </div>
          </li>
        </ul>
      </li>

      <!-- Section 3: Subgroup C1 y C3 -->
      <li class="section main clearfix" id="section-3">
        <h3 class="sectionname">Prácticas (Grupos C1 y C3)</h3>
        <ul class="section img-text">
          <li class="activity modtype_resource" id="module-107915">
            <div class="activityinstance">
              <a href="https://pradogrado2627.ugr.es/mod/resource/view.php?id=107915">
                <span class="instancename">Guion Práctica 1 - Grupos C1 y C3 Archivo</span>
              </a>
            </div>
          </li>
        </ul>
      </li>

      <!-- Section 4: Subgroup C2 -->
      <li class="section main clearfix" id="section-4">
        <h3 class="sectionname">Prácticas (Grupo C2)</h3>
        <ul class="section img-text">
          <li class="activity modtype_resource" id="module-107916">
            <div class="activityinstance">
              <a href="https://pradogrado2627.ugr.es/mod/resource/view.php?id=107916">
                <span class="instancename">Guion Práctica 1 - Grupo C2 Archivo</span>
              </a>
            </div>
          </li>
          <li class="activity modtype_assign" id="module-107917">
            <div class="activityinstance">
              <a href="https://pradogrado2627.ugr.es/mod/assign/view.php?id=107917">
                <span class="instancename">Entrega y Enunciado Práctica 1 Tarea</span>
              </a>
            </div>
          </li>
        </ul>
      </li>
    </ul>
  </div>
</body>
</html>
"""

MOODLE_FOLDER_107914_HTML = """<!DOCTYPE html>
<html>
<head><title>Material Adicional Árboles AVL</title></head>
<body>
  <div class="foldertree">
    <div class="fp-filename-icon">
      <a href="https://pradogrado2627.ugr.es/pluginfile.php/15819/mod_folder/content/1/arboles_avl.pdf">
        arboles_avl.pdf
      </a>
    </div>
    <div class="fp-filename-icon">
      <a href="https://pradogrado2627.ugr.es/pluginfile.php/15819/mod_folder/content/1/arboles_b.pdf">
        arboles_b.pdf
      </a>
    </div>
  </div>
</body>
</html>
"""

MOODLE_ASSIGN_107917_HTML = """<!DOCTYPE html>
<html>
<head><title>Entrega Práctica 1</title></head>
<body>
  <h2>Entrega y Enunciado Práctica 1</h2>
  <div class="introattachment">
    <a href="https://pradogrado2627.ugr.es/pluginfile.php/15819/mod_assign/introattachment/0/Practica_1_starter.ipynb">
      Practica_1_starter.ipynb
    </a>
  </div>
  <div data-region="activity-dates">
    <div>Apertura: martes, 20 de octubre de 2026, 00:00</div>
    <div>Cierre: lunes, 14 de diciembre de 2026, 23:59</div>
  </div>
  <table class="generaltable submissionstatustable">
    <tr>
      <td>Estado de la entrega</td>
      <td>Sin entregar</td>
    </tr>
    <tr>
      <td>Estado de la calificación</td>
      <td>Sin calificar</td>
    </tr>
    <tr>
      <td>Fecha de entrega</td>
      <td>lunes, 14 de diciembre de 2026, 23:59</td>
    </tr>
  </table>
</body>
</html>
"""

MOODLE_FORUM_107901_HTML = """<!DOCTYPE html>
<html>
<head><title>Avisos y Novedades del Curso</title></head>
<body>
  <h2>Avisos del Profesorado</h2>
  <article class="forum-post-container" id="post-1">
    <h3 class="h4 post-subject">Calendario de Prácticas y Tutorías</h3>
    <div class="author">Prof. Miguel García Silvente - martes, 27 de octubre de 2026, 12:00</div>
    <div class="post-content">
      Se recuerda a todos los alumnos que la revisión de la prueba de laboratorio tendrá lugar en el despacho 19.
    </div>
  </article>
</body>
</html>
"""

SAMPLE_PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\nxref\n0 3\n0000000000 65535 f\ntrailer<</Size 3/Root 1 0 R>>\nstartxref\n120\n%%EOF\n"
SAMPLE_IPYNB_CONTENT = json.dumps({
    "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Practica 1 - Eficiencia\n"]},
        {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["print('Lab ready')\n"]}
    ],
    "metadata": {"language_info": {"name": "python"}},
    "nbformat": 4,
    "nbformat_minor": 2
}).encode("utf-8")


# -----------------------------------------------------------------------------
# 2. Mock HTTP Transport Adapter (Simulates PRADO & SimpleSAMLphp IdP)
# -----------------------------------------------------------------------------

class MockPradoTransport(HTTPAdapter):
    """
    A comprehensive mock HTTPAdapter simulating:
    - SimpleSAMLphp IdP redirection and credentials verification
    - 3-Tier MFA challenges and 30-day device trust token generation
    - Moodle session cookie management (MoodleSession, MFA_TOKEN_*)
    - Moodle AJAX course discovery (/lib/ajax/service.php)
    - Course page, section, activity, folder, assignment HTML scraping
    - Streaming chunked file downloads with Content-Disposition headers
    """

    def __init__(
        self,
        valid_user: str = "testuser@correo.ugr.es",
        valid_pass: str = "correct_password_123",
        valid_mfa_code: str = "123456",
        base_url: str = "https://pradogrado2627.ugr.es",
        idp_url: str = "https://idp.ugr.es",
    ):
        super().__init__()
        self.valid_user = valid_user
        self.valid_pass = valid_pass
        self.valid_mfa_code = valid_mfa_code
        self.base_url = base_url.rstrip("/")
        self.idp_url = idp_url.rstrip("/")

        # Server-side state
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.active_mfa_tokens: Dict[str, float] = {}  # token -> expiry epoch
        self.download_counts: Dict[str, int] = {}
        self.simulate_network_timeout: bool = False
        self.simulate_corrupted_stream: bool = False

    def build_response(
        self,
        request: requests.PreparedRequest,
        status_code: int = 200,
        content: bytes | str = b"",
        headers: Optional[Dict[str, str]] = None,
        reason: Optional[str] = None,
    ) -> Response:
        resp = Response()
        resp.status_code = status_code
        resp.url = request.url
        resp.request = request
        resp.reason = reason or "OK"

        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content

        resp.raw = io.BytesIO(content_bytes)

        resp_headers = CaseInsensitiveDict({
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(content_bytes)),
        })
        if headers:
            resp_headers.update(headers)
        resp.headers = resp_headers
        return resp

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> Response:
        if self.simulate_network_timeout:
            raise requests.exceptions.Timeout("Mock simulated network timeout")

        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method or "GET"

        # Cookie inspection from request headers
        req_cookie_header = request.headers.get("Cookie", "")
        req_cookies: Dict[str, str] = {}
        if req_cookie_header:
            for item in req_cookie_header.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    req_cookies[k] = v

        # --- SimpleSAMLphp SSO Endpoints ---

        # 1. Initial SP login redirect
        if path == "/auth/saml2/login.php":
            headers = {
                "Location": f"{self.idp_url}/simplesaml/module.php/core/loginuserpass?AuthState=_authState_valid_token_12345"
            }
            return self.build_response(request, status_code=302, headers=headers)

        # 2. IdP login form (GET)
        if path == "/simplesaml/module.php/core/loginuserpass" and method == "GET":
            query = parse_qs(parsed.query)
            if "retryURL" in query or "_authState_refreshed" in parsed.query:
                return self.build_response(request, status_code=200, content=SAML_IDP_LOGIN_HTML)
            return self.build_response(request, status_code=200, content=SAML_IDP_LOGIN_HTML)

        # 3. IdP credentials POST
        if path == "/simplesaml/module.php/core/loginuserpass" and method == "POST":
            body = request.body or ""
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="ignore")
            form_data = parse_qs(body)
            username = form_data.get("username", [""])[0]
            password = form_data.get("password", [""])[0]

            if username == "locked_user@correo.ugr.es":
                return self.build_response(request, status_code=200, content=SAML_IDP_LOCKED_HTML)

            if username != self.valid_user or password != self.valid_pass:
                return self.build_response(request, status_code=200, content=SAML_IDP_INVALID_CREDS_HTML)

            # Valid credentials -> return SAML auto-post form
            return self.build_response(request, status_code=200, content=SAML_ASSERTION_POST_HTML)

        # 4. SP Assertion Consumer Service (ACS) POST
        if "/auth/saml2/sp/saml2-acs.php" in path and method == "POST":
            # Check for existing valid 30-day device trust token
            has_device_trust = any(
                k.startswith("MFA_TOKEN_") and self.active_mfa_tokens.get(v, 0) > time.time()
                for k, v in req_cookies.items()
            )

            sess_token = f"sess_{os.urandom(8).hex()}"
            self.active_sessions[sess_token] = {"authenticated": True, "user": self.valid_user}

            set_cookie_parts = [
                f"MoodleSession={sess_token}; Path=/; HttpOnly",
                f"MOODLEID1_={os.urandom(6).hex()}; Path=/",
            ]

            if has_device_trust:
                # Direct redirect to /my/
                headers = {
                    "Location": f"{self.base_url}/my/",
                    "Set-Cookie": ", ".join(set_cookie_parts),
                }
                return self.build_response(request, status_code=302, headers=headers)
            else:
                # Redirect to MFA challenge
                headers = {
                    "Location": f"{self.base_url}/admin/tool/mfa/auth.php",
                    "Set-Cookie": ", ".join(set_cookie_parts),
                }
                return self.build_response(request, status_code=302, headers=headers)

        # 5. Moodle MFA Challenge GET
        if path == "/admin/tool/mfa/auth.php" and method == "GET":
            return self.build_response(request, status_code=200, content=MFA_CHALLENGE_HTML)

        # 6. Moodle MFA Challenge POST
        if path == "/admin/tool/mfa/auth.php" and method == "POST":
            body = request.body or ""
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="ignore")
            form_data = parse_qs(body)
            code = form_data.get("verificationcode", [""])[0]
            trust = form_data.get("factor_token_trust", ["0"])[0] == "1"

            if code != self.valid_mfa_code:
                return self.build_response(request, status_code=200, content=MFA_ERROR_HTML)

            headers: Dict[str, str] = {"Location": f"{self.base_url}/my/"}
            if trust:
                token_val = f"token_{os.urandom(8).hex()}"
                expiry = time.time() + (30 * 86400)
                self.active_mfa_tokens[token_val] = expiry
                headers["Set-Cookie"] = (
                    f"MFA_TOKEN_trust_hash={token_val}; Path=/; Max-Age=2592000; HttpOnly"
                )

            return self.build_response(request, status_code=302, headers=headers)

        # --- Moodle Application Endpoints ---

        # 7. Dashboard /my/
        if path in ("/my/", "/my"):
            # Check authenticated session
            sess_cookie = req_cookies.get("MoodleSession")
            if not sess_cookie or sess_cookie not in self.active_sessions:
                # Not logged in -> redirect to login
                return self.build_response(
                    request, status_code=302, headers={"Location": f"{self.base_url}/auth/saml2/login.php"}
                )
            return self.build_response(request, status_code=200, content=MOODLE_MY_DASHBOARD_HTML)

        # 8. Moodle AJAX Web Service
        if path == "/lib/ajax/service.php":
            sess_cookie = req_cookies.get("MoodleSession")
            if not sess_cookie:
                return self.build_response(request, status_code=403, content=json.dumps({"error": "Forbidden"}))
            ajax_resp = [
                {
                    "data": {
                        "courses": MOODLE_AJAX_COURSES_DATA,
                        "nextoffset": 5,
                    }
                }
            ]
            return self.build_response(
                request,
                status_code=200,
                content=json.dumps(ajax_resp),
                headers={"Content-Type": "application/json"},
            )

        # 9. Course View
        if path == "/course/view.php":
            return self.build_response(request, status_code=200, content=MOODLE_COURSE_15819_HTML)

        # 10. Folder View
        if path == "/mod/folder/view.php":
            return self.build_response(request, status_code=200, content=MOODLE_FOLDER_107914_HTML)

        # 11. Assignment View
        if path == "/mod/assign/view.php":
            return self.build_response(request, status_code=200, content=MOODLE_ASSIGN_107917_HTML)

        # 12. Forum View
        if path == "/mod/forum/view.php":
            return self.build_response(request, status_code=200, content=MOODLE_FORUM_107901_HTML)

        # 13. Resource file downloads
        if path == "/mod/resource/view.php":
            query = parse_qs(parsed.query)
            mod_id = query.get("id", ["0"])[0]
            self.download_counts[mod_id] = self.download_counts.get(mod_id, 0) + 1

            if self.simulate_corrupted_stream:
                content = b"%PDF-1.4 [corrupted-truncated"
            else:
                content = SAMPLE_PDF_BYTES

            filename = f"recurso_{mod_id}.pdf"
            if mod_id == "107913":
                filename = "Tema_1_Eficiencia.pdf"
            elif mod_id == "107916":
                filename = "Guion_P1_C2.pdf"

            headers = {
                "Content-Type": "application/pdf",
                "Content-Disposition": f'attachment; filename="{filename}"',
            }
            return self.build_response(request, status_code=200, content=content, headers=headers)

        # 14. Pluginfile download (Folder or Assignment Attachment)
        if "/pluginfile.php/" in path:
            filename = path.split("/")[-1]
            self.download_counts[filename] = self.download_counts.get(filename, 0) + 1

            if filename.endswith(".ipynb"):
                content = SAMPLE_IPYNB_CONTENT
                content_type = "application/x-ipynb+json"
            else:
                content = SAMPLE_PDF_BYTES
                content_type = "application/pdf"

            headers = {
                "Content-Type": content_type,
                "Content-Disposition": f'attachment; filename="{filename}"',
            }
            return self.build_response(request, status_code=200, content=content, headers=headers)

        # Fallback 404
        return self.build_response(request, status_code=404, content="Not Found")


# -----------------------------------------------------------------------------
# 3. Core Pytest Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def mock_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Creates an isolated temporary configuration directory (~/.config/prado)
    with strict mode 0700 permissions and points PRADO_CONFIG_DIR to it.
    """
    cfg_dir = tmp_path / "prado_config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(cfg_dir, 0o700)
    monkeypatch.setenv("PRADO_CONFIG_DIR", str(cfg_dir))
    return cfg_dir


@pytest.fixture
def mock_courses_dir(tmp_path: Path) -> Path:
    """
    Creates an isolated destination directory for student courses and downloads.
    """
    courses_dir = tmp_path / "student_courses"
    courses_dir.mkdir(parents=True, exist_ok=True)
    return courses_dir


@pytest.fixture
def in_memory_keyring(monkeypatch: pytest.MonkeyPatch) -> Dict[Tuple[str, str], str]:
    """
    Provides an in-memory key-value dictionary simulating the OS secure keyring.
    Prevents tests from modifying the real host OS Keychain / Credential Manager.
    """
    keyring_store: Dict[Tuple[str, str], str] = {}

    def mock_get_password(service_name: str, username: str) -> Optional[str]:
        return keyring_store.get((service_name, username))

    def mock_set_password(service_name: str, username: str, password: str) -> None:
        keyring_store[(service_name, username)] = password

    def mock_delete_password(service_name: str, username: str) -> None:
        keyring_store.pop((service_name, username), None)

    import keyring
    monkeypatch.setattr(keyring, "get_password", mock_get_password)
    monkeypatch.setattr(keyring, "set_password", mock_set_password)
    monkeypatch.setattr(keyring, "delete_password", mock_delete_password)
    return keyring_store


@pytest.fixture
def mock_prado_transport() -> MockPradoTransport:
    """
    Provides a configured MockPradoTransport instance for mounting on requests.Session.
    """
    return MockPradoTransport()


@pytest.fixture
def mock_http_session(mock_prado_transport: MockPradoTransport) -> requests.Session:
    """
    Provides a requests.Session mounted with MockPradoTransport intercepting
    requests to https://pradogrado2627.ugr.es and https://idp.ugr.es.
    """
    session = requests.Session()
    session.mount("https://pradogrado2627.ugr.es", mock_prado_transport)
    session.mount("https://idp.ugr.es", mock_prado_transport)
    return session


@pytest.fixture
def sample_html_fixtures() -> Dict[str, Any]:
    """
    Dictionary exposing all authoritative HTML / JSON sample fixtures.
    """
    return {
        "saml_idp_login": SAML_IDP_LOGIN_HTML,
        "saml_idp_retry": SAML_IDP_RETRY_HTML,
        "saml_idp_invalid_creds": SAML_IDP_INVALID_CREDS_HTML,
        "saml_idp_locked": SAML_IDP_LOCKED_HTML,
        "saml_assertion_post": SAML_ASSERTION_POST_HTML,
        "mfa_challenge": MFA_CHALLENGE_HTML,
        "mfa_error": MFA_ERROR_HTML,
        "moodle_dashboard": MOODLE_MY_DASHBOARD_HTML,
        "moodle_ajax_courses": MOODLE_AJAX_COURSES_DATA,
        "moodle_course_15819": MOODLE_COURSE_15819_HTML,
        "moodle_folder_107914": MOODLE_FOLDER_107914_HTML,
        "moodle_assign_107917": MOODLE_ASSIGN_107917_HTML,
        "moodle_forum_107901": MOODLE_FORUM_107901_HTML,
        "sample_pdf_bytes": SAMPLE_PDF_BYTES,
        "sample_ipynb_content": SAMPLE_IPYNB_CONTENT,
    }
