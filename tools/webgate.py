from http.server import HTTPServer, SimpleHTTPRequestHandler
from base64 import b64decode

import ssl
import textwrap
import uuid
import xml.etree.ElementTree as ET

USERS = {
    'user1@example.com': ("FA520EE2-4419-4EB4-AE49-6E9ABE6EF24F", "D8B9BF5D-90B1-4CBD-9B76-88DA7BE763B6"),
    'user2@example.com': ("5FB222BC-9D19-4308-AC3E-3C62685BC6AE", "224AEE30-D8A5-4F18-AD8E-B5FCBF121C4E"),
    'user3@example.com': ("9957C79C-B93C-4B60-9D84-9F38A1F62BE3", "CCDB4B8D-1C88-48C0-BDA0-0A5E8D87F4DA"),
}

sessions = {}

class InvalidSession(RuntimeError):
    def __init__(self, authorization):
        self.authorization = authorization

    def __str__(self):
        print(f'InvalidSession(id: "{self.authorization})"')

class Session:
    def __init__(self, session_id):
        self.session_id = session_id

    def id(self):
        return str(self.session_id).upper()

class ServerHandler(SimpleHTTPRequestHandler):
    def _set_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def get_session_create(self):
        session = Session(uuid.uuid4())
        session_id = session.id()
        sessions[session_id] = session

        resp = textwrap.dedent(f'''
            <Reply>
            <Session>{session_id}</Session>
            </Reply>
        ''').lstrip('\n').encode()

        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(resp)

    def get_session(self):
        authorization = self.headers['Authorization']
        if not authorization.startswith('Arena '):
            raise InvalidSession(authorization)
        session_id = authorization[len('Arena '):]
        if not session_id in sessions:
            raise InvalidSession(authorization)
        return sessions[session_id]

    def handle_users_login(self):
        session = self.get_session()

        length = int(self.headers['Content-Length'])
        payload = self.rfile.read(length).decode('utf8')
        root = ET.fromstring(payload)

        provider = root.find('Provider').text
        if provider == 'Portal':
            email = root.find('LoginName').text
            password = b64decode(root.find('Password').text)
            game_code = root.find('GameCode').text

            if not email in USERS:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'who are you?')
                return

            user_id, token_id = USERS[email]
            session.email = email
            session.user_id = user_id
            session.token_id = token_id

            resp = textwrap.dedent(f'''
                <Reply>
                <UserId>{user_id}</UserId>
                <UserCenter>1</UserCenter>
                <UserName>:John.10</UserName>
                <Parts/>
                <ResumeToken>AAAAAAAA-BBBB-CCCC-DDDD-FFFFFFFFFFFF</ResumeToken>
                <LoginName>{email}</LoginName>
                <Provider>{provider}</Provider>
                <EmailVerified>1</EmailVerified>
                </Reply>
            ''').lstrip('\n').encode()

            self.send_response(200)
            self.send_header('Content-Type', 'application/xml')
            self.end_headers()
            self.wfile.write(resp)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Unsupported provider')

    def handle_game_accounts(self):
        session = self.get_session()

        length = int(self.headers['Content-Length'])
        payload = self.rfile.read(length).decode('utf8')
        root = ET.fromstring(payload)

        game_code = root.find('GameCode').text
        resp = textwrap.dedent(f'''
            <Reply type="array">
            <Row>
            <GameCode>{game_code}</GameCode>
            <Alias>gw1</Alias>
            <Created>2005-01-01T12:00:00Z</Created>
            </Row>
            </Reply>
        ''').lstrip('\n').encode()

        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(resp)

    def handle_game_token(self):
        session = self.get_session()

        length = int(self.headers['Content-Length'])
        payload = self.rfile.read(length).decode('utf8')
        root = ET.fromstring(payload)

        game = root.find('GameCode').text
        alias = root.find('AccountAlias').text

        resp = textwrap.dedent(f'''
            <Reply>
            <Token>{session.token_id}</Token>
            </Reply>
        ''').lstrip('\n').encode()

        self.send_response(200)
        self.send_header('Content-Type', 'application/xml')
        self.end_headers()
        self.wfile.write(resp)

    def do_GET(self):
        if self.path == '/Spawned/WebGate/session/create.xml':
            self.get_session_create()
        else:
            print('GET', self.path)

    def do_POST(self):
        try:
            if self.path == '/Spawned/WebGate/users/login.xml':
                self.handle_users_login()
            elif self.path == '/Spawned/WebGate/my_account/game_accounts.xml':
                self.handle_game_accounts()
            elif self.path == '/Spawned/WebGate/my_account/token.xml':
                self.handle_game_token()
            else:
                print('POST', self.path)
        except InvalidSession:
            self.send_response(401)

http = HTTPServer(('localhost', 6601), ServerHandler)
http.serve_forever()
