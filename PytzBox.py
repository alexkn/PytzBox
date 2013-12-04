
import urllib
import urllib2
import re
import socket
import hashlib
import mimetools
import xml.sax


__doc__="""
PytzBox

usage:
  ./PytzBox.py getphonebook [--host=<fritz.box>] [--username=<user>] [--password=<pass>] [--id=<int>]
  ./PytzBox.py getphonebooklist [--host=<fritz.box>] [--username=<user>] [--password=<pass>]

options:
  --username=<user>     username usually not required
  --password=<pass>     admin password [default: none]
  --host=<fritz.box>    ip address / hostname [default: fritz.box]

"""

class PytzBox:

    __password = False
    __host = False
    __user = False
    __sid = None
    __protocol = 'http'
    __login_requirement = 0

    __url_login_webcm        = '{protocol}://{host}/cgi-bin/webcm'
    __url_login_fmwcfg       = '{protocol}://{host}/cgi-bin/firmwarecfg'
    __url_phonebook_list     = '{protocol}://{host}/fon_num/fonbook_select.lua?sid={sid}'
    __url_sid_lua_challenge  = '{protocol}://{host}//login_sid.lua'
    __data_sid_challenge     = 'getpage=../html/login_sid.xml'
    __data_login_legacy      = 'getpage=../html/de/menus/menu2.html&errorpage=../html/index.html&var:lang=de&var:pagename=home&var:menu=home&=&login:command/password={password}'
    __data_login_sid         = 'login:command/response={response}&getpage=../html/login_sid.xml'
    __url_file_download      = '{protocol}://{host}/nas/cgi-bin/luacgi_notimeout?sid={sid}&script=%2fhttp_file_download.lua&command=httpdownload&cmd_files={path}'

    class LoginRequiredException(Exception): pass
    class UnkownLoginVersionException(Exception): pass
    class BoxUnreachableException(Exception): pass
    class UnsupportedCharInPasswordException(Exception): pass
    class LoginFailedException(Exception): pass
    class RequestFailedException(Exception): pass

    def __init__(self, password=False, host="fritz.box", username=False):

        socket.setdefaulttimeout(10)

        self.__password = password
        self.__host = host
        if username:
            self.__user = username

        self.__login_requirement = self.__requireLogin()

        if self.__login_requirement and self.__password is False:
            raise self.LoginRequiredException('no password given')


    def __requireLogin(self):

        try:
            response = urllib2.urlopen(
                self.__url_login_webcm.format(protocol=self.__protocol, host=self.__host),
                self.__data_sid_challenge
            )
        except socket.error, e:
            raise self.BoxUnreachableException(str(e))
        except IOError, e:
            raise self.BoxUnreachableException(str(e))
        else:
            if response.getcode() != 200:
                # 1st style
                return 1
            else:
                # 2nd style
                is_write_access_match = re.search(r".*<iswriteaccess>(\d)</iswriteaccess>.*", response.read(), re.MULTILINE | re.IGNORECASE)
                sid_match = re.search('<SID>(.*?)</SID>', response.read())
                if is_write_access_match:
                    write_access_result = int(is_write_access_match.group(1))
                    if write_access_result == 0:
                        if sid_match and int(sid_match.group(1)) != 0:
                            self.__sid = sid_match.group(1)
                            return 0
                        else:
                            return 2
        try:
            response = urllib2.urlopen(
                self.__url_sid_lua_challenge.format(protocol=self.__protocol, host=self.__host)
            )
        except socket.error, e:
            raise self.BoxUnreachableException(str(e))
        except IOError, e:
            raise self.BoxUnreachableException(str(e))
        else:
            is_session_info_match = re.search(r".*<SessionInfo>.*</SessionInfo>.*", response.read(), re.MULTILINE | re.IGNORECASE)
            if is_session_info_match:
                # 3rd style
                sid_match = re.search('<SID>(.*?)</SID>', response.read())
                if sid_match and int(sid_match.group(1)) != 0:
                    self.__sid = sid_match.group(1)
                    return 0
                else:
                    return 3
            print response.read()

        return 0


    def __loginSid(self):

        # request challenge
        try:
            if self.__login_requirement == 2:
                response = urllib2.urlopen(
                    self.__url_login_webcm.format(protocol=self.__protocol, host=self.__host),
                    self.__data_sid_challenge
                )
            elif self.__login_requirement == 3:
                response = urllib2.urlopen(
                    self.__url_sid_lua_challenge.format(protocol=self.__protocol, host=self.__host)
                )
        except socket.error, e:
            raise self.BoxUnreachableException(str(e))
        except IOError, e:
            raise self.BoxUnreachableException(str(e))
        else:
            if response.getcode() != 200:
                raise self.LoginFailedException('unknown returncode')

        # get challenge string
        challenge_match = re.search(r".*<Challenge>([A-Za-z0-9]*)</Challenge>.*", response.read(), re.MULTILINE | re.IGNORECASE)
        if challenge_match:
            challenge_string = challenge_match.group(1)
        else:
            raise self.LoginFailedException('challenge string not found')

        # Create a UTF-16LE string from challenge + '-' + password
        try:
            challenge_bf = ("%s-%s" % (challenge_string, str(self.__password))).decode('iso-8859-1').encode('utf-16le')
        except UnicodeError:
            #non ISO-8859-1 characters will except here (e.g. EUR)
            raise self.UnsupportedCharInPasswordException()

        # Calculate the MD5 hash
        m = hashlib.md5()
        m.update(challenge_bf)

        # byte response string from challenge + '-' + md5_hex_value
        response_bf = "%s-%s" % (challenge_string, m.hexdigest().lower())

        # Answer the challenge
        try:
            if self.__login_requirement == 2:
                response = urllib2.urlopen(
                    self.__url_login_webcm.format(protocol=self.__protocol, host=self.__host),
                    self.__data_login_sid.format(response=response_bf)
                )
            elif self.__login_requirement == 3:
                username=''
                if self.__user:
                    username=self.__user
                response = urllib2.urlopen(
                    self.__url_sid_lua_challenge.format(protocol=self.__protocol, host=self.__host),
                    urllib.urlencode(dict(response=response_bf, username=username))
                )
        except socket.error, e:
            raise self.BoxUnreachableException(str(e))
        except IOError, e:
            raise self.BoxUnreachableException(str(e))
        else:
            if response.getcode() != 200:
                raise self.LoginFailedException('unknown returncode')

        # search sid
        search = re.search('<SID>(.*?)</SID>', response.read())
        if search:
            self.__sid = search.group(1)
            try:
                if int(self.__sid) == 0:
                    raise self.LoginFailedException('could not login (sid is %s)' % self.__sid)
            except ValueError:
                pass
            return True
        else:
            return False


    def __loginLegacy(self):

        try:
            response = urllib2.urlopen(
                self.__url_login_webcm.format(protocol=self.__protocol, host=self.__host),
                self.__data_login_legacy.format(password=self.__password)
            )
        except socket.error, e:
            raise self.BoxUnreachableException(str(e))
        except IOError, e:
            raise self.BoxUnreachableException(str(e))
        else:
            response.getcode()
            if response.getcode() == 200:
                try:
                    match = re.search('<p class="errorMessage">(.*?)</p>', response.read())
                    if match:
                        return False
                except Exception, e:
                    raise self.LoginFailedException(str(e))
                else:
                    self.__sid = False
                    return True
            else:
                raise self.LoginFailedException('unknown returncode')


    class __encodeMultipartFormdata:

        content_type = None
        body = None

        def __init__(self, fields):
            boundary = mimetools.choose_boundary()
            end_line = '\r\n'
            result = list()
            for (key, value) in fields:
                result.append('--' + boundary)
                result.append('Content-Disposition: form-data; name="%s"' % key)
                result.append('')
                result.append(value)
            result.append('--' + boundary + '--')
            result.append('')
            self.body = end_line.join(result)
            self.content_type = 'multipart/form-data; boundary=%s' % boundary


    def __analyzeFritzboxPhonebook(self, xml_phonebook):

        class FbAbHandler(xml.sax.ContentHandler):

            def __init__(self, parent):
                self.contact_name = ""
                self.key       = None
                self.parent       = parent
                self.phone_book   = dict()

            #noinspection PyUnusedLocal
            def startElement(self,  name, args):
                if name == "contact":
                    self.contact_name = ""
                self.key = name

            def endElement (self,  name):
                self.key = None

            def characters(self,  content):
                #print("%s: %s" % (self.key, content))
                if self.key == "realName":
                    self.contact_name = content
                    if not self.contact_name in self.phone_book:
                        self.phone_book[self.contact_name] = { 'numbers': [] }
                if self.key == "number":
                    if self.contact_name in self.phone_book:
                        self.phone_book[self.contact_name]['numbers'].append(content)
                if self.key == "imageURL":
                    if self.contact_name in self.phone_book:
                        self.phone_book[self.contact_name]['imageURL'] = content
                        self.phone_book[self.contact_name]['imageHttpURL'] = self.parent.getDownloadUrl(content)

        handler = FbAbHandler(self)

        try:
            xml.sax.parseString(xml_phonebook, handler=handler)
        except Exception, e:
            raise ValueError('could not parse phonebook data (are you logged in?): %s' % str(e))

        return handler.phone_book




    def sid(self):

        if self.__sid is not None:
            return self.__sid
        else:
            return False


    def login(self):
        if self.__login_requirement is False:
            pass
        elif self.__login_requirement == 3:
            self.__loginSid()
        elif self.__login_requirement == 2:
            self.__loginSid()
        elif self.__login_requirement == 1:
            self.__loginLegacy()
        else: raise self.UnkownLoginVersionException(self.__login_requirement)

        return self


    def getDownloadUrl(self, base):
        if base.startswith('file:///var/media/ftp/'):
            file_path = "/%s://" % base.lstrip('file:///var/media/ftp/')
            try:
                return self.__url_file_download.format(
                        protocol=urllib.quote(self.__protocol),
                        host=urllib.quote(self.__host),
                        sid=urllib.quote(self.__sid),
                        path=urllib.quote(file_path)
                    )
            except Exception, e:
                print e
        else:
            return base

    def getPhonebookList(self):
        if self.__sid is None:
            raise self.LoginRequiredException()

        request = urllib2.Request(
            self.__url_phonebook_list.format(protocol=self.__protocol, host=self.__host, sid=self.__sid)
        )

        try:
            response = urllib2.urlopen(request, timeout=5)
        except socket, e:
            raise self.BoxUnreachableException(str(e))
        except IOError, e:
            raise self.BoxUnreachableException(str(e))
        except Exception, e:
            raise self.RequestFailedException(str(e))
        else:
            response =  response.read()

            phonbook_ids = re.findall(r'uiBookid:(\d*)', response)

            if phonbook_ids:
                return list(set(phonbook_ids))

        return False

    def getPhonebook(self, id=0, name='Phonebook'):

        if self.__sid is None:
            raise self.LoginRequiredException()

        data = self.__encodeMultipartFormdata( (
            ('sid', self.__sid),
            ('PhonebookId', str(id)),
            ('PhonebookExportName', str(name)),
            ('PhonebookExport', '')
            )
        )

        request = urllib2.Request(
            self.__url_login_fmwcfg.format(protocol=self.__protocol, host=self.__host),
            data.body,
            headers={'Content-Type': data.content_type}
        )

        try:
            response = urllib2.urlopen(request, timeout=5)
        except socket, e:
            raise self.BoxUnreachableException(str(e))
        except IOError, e:
            raise self.BoxUnreachableException(str(e))
        except Exception, e:
            raise self.RequestFailedException(str(e))
        else:
            xml_phonebook =  response.read()

        return self.__analyzeFritzboxPhonebook(xml_phonebook)



if __name__ == '__main__':

    import docopt

    arguments = docopt.docopt(__doc__);

    from pprint import pprint

    box = PytzBox(username=arguments['--username'], password=arguments['--password'], host=arguments['--host']).login()

    if arguments['getphonebook']:
        pprint( box.getPhonebook(id=arguments['--id'] and arguments['--id'] or 0) )
    elif arguments['getphonebooklist']:
        pprint( box.getPhonebookList() )
