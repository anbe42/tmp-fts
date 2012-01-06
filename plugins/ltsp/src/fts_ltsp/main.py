# -*- coding: utf-8 -*-
import ldap
import ldap.filter
import os
import syslog
import re
from fts.ldap_utils import LDAPHandler
from fts.bootplugin import BootPlugin


class LTSPBoot(BootPlugin):

    def __init__(self):
        super(LTSPBoot, self).__init__()

        self.ldap = LDAPHandler.get_instance()
        self.server = self.config.get('ltsp.server', 'localhost')
        self.nfs_opts= self.config.get('fai.nfs-opts', 'nfs4')
        self.fai_flags= self.config.get('fai.flags', 'verbose,sshd,syslogd,createvt,reboot')
        self.union= self.config.get('fai.union', 'unionfs')
        self.default_init= self.config.get('tftp.default-init', 'fallback')
        self.tftp_root = os.path.dirname(self.config.get('tftp.path', '/srv/fai/boot'))

    def getBootParams(self, address):
        result = None
        with self.ldap.get_handle() as conn:
            res = conn.search_s(
                self.ldap.get_base(),
                ldap.SCOPE_SUBTREE,
                ldap.filter.filter_format("(&(macAddress=%s)(objectClass=gotoTerminal))", [address]),
                ['gotoTerminalPath', 'gotoBootKernel', 'gotoKernelParameters', 'gotoLdapServer', 'cn'])

            if res is not None:
                count = len(res)
                if count > 1:
                    syslog.syslog("[ltsp] ignoring %s - LDAP search is not unique (%d entries match)" % (address, res.count()))
                    return None

                if count == 1:
                    dn, attributes = res[0]
                    hostname = attributes.get('cn', [''])[0]

                    kernel = attributes.get('gotoBootKernel', [''])[0]
                    nfsroot = attributes.get('gotoTerminalPath', [''])[0]
                    ldap_server = attributes.get('gotoLdapServer', [''])[0]
                    cmdline = attributes.get('gotoKernelParameters', [''])[0]

                    if not kernel or not ldap_server or not cmdline or not nfsroot:
                        # Check group membership
                        member_res = conn.search_s(
                            self.ldap.get_base(),
                            ldap.SCOPE_SUBTREE,
                            ldap.filter.filter_format("(&(member=%s)(objectClass=gosaGroupOfNames)(gosaGroupObjects=[T]))", [dn]),
                            ['gotoBootKernel', 'gotoKernelParameters', 'gotoLdapServer', 'cn', 'gotoTerminalPath'])
                        if member_res is not None:
                            group_count = len(member_res)
                            if group_count > 1:
                                syslog.syslog(syslog.LOG_ERR, "[ltsp] Found more than one group for host {hostname}!")
                                return None

                            if group_count == 1:
                                group_dn, group_attributes = member_res[0]

                                if not kernel:
                                    kernel = group_attributes.get('gotoBootKernel', [''])[0]

                                if not ldap_server:
                                    ldap_server = group_attributes.get('gotoLdapServer', [''])[0]

                                if not cmdline:
                                    cmdline = group_attributes.get('gotoKernelParameters', [''])[0]

                                if not nfsroot:
                                    nfsroot = group_attributes.get('gotoTerminalPath', [''])[0]

                            if group_count == 0:
                                syslog.syslog(syslog.LOG_INFO, "[ltsp] {hostname} - no group membership found - aborting".format(hostname=hostname))

                    if not kernel or not ldap_server or not cmdline or not nfsroot:
                        line = "{hostname} - missing attribute(s) -".format(hostname=hostname)
                        if not kernel:
                            line = line + " gotoBootKernel"
                        if not ldap_server:
                            line = line + " gotoLdapServer"
                        if not cmdline:
                            line = line + " gotoKernelParameters"
                        if not nfsroot:
                            line = line + " gotoTerminalPath"
                        syslog.syslog(syslog.LOG_ERR, line)
                        return None

                    # Strip ldap parameter and all multiple and trailing spaces
                    cmdline = re.sub(r'ldap(=[^\s]*[\s]*|[\s]*$|\s+)', '', cmdline)
                    cmdline = re.sub(r'\s[\s]+', '', cmdline.strip())

                    # Get kernel and initrd from TFTP root

                    # - extract kernel version
                    kernel_version='install'
                    if kernel.startswith('vmlinuz-'):
                        kernel_version = kernel[8:]
                    elif kernel.startswith('linux-image-'):
                        kernel_version = kernel[12:]

                    # # - guess filename for kernel
                    # if not os.access(self.tftp_root + os.sep + kernel, os.F_OK):
                    #     # Try default kernel
                    #     if os.access(self.tftp_root + os.sep + 'vmlinuz-' + kernel_version, os.F_OK):
                    #         syslog.syslog(syslog.LOG_INFO, "{hostname} - specified kernel {kernel} does not exist, using 'vmlinuz-{version}'".format(hostname=hostname, kernel=kernel, version=kernel_version))
                    #         kernel = 'vmlinuz-' + kernel_version
                    #     elif os.access(self.tftp_root + os.sep + 'vmlinuz-install', os.F_OK):
                    #         syslog.syslog(syslog.LOG_INFO, "{hostname} - specified kernel {kernel} does not exist, using 'vmlinuz-install'".format(hostname=hostname, kernel=kernel))
                    #         kernel = 'vmlinuz-install'
                    #     else:
                    #         syslog.syslog(syslog.LOG_ERR, "{hostname} - specified kernel {kernel} does not exist!".format(hostname=hostname, kernel=kernel))
                    #         return None

                    # # - try to find the initrd
                    # path = self.tftp_root + os.sep + 'initrd.img-' + kernel_version
                    # if os.access(path, os.F_OK):
                    #     cmdline = cmdline + " initrd=initrd.img-" + kernel_version
                    #     cmdline = cmdline.strip()

                    # # Add NFS options
                    # cmdline = cmdline + " nfsroot=" + self.nfs_root + "," + self.nfs_opts
                    # cmdline = cmdline.strip()

                    # result = self.make_pxe_entry(kernel=kernel, append=cmdline)
                    return result

        return None

    def getInfo(self):
        return "LTSP - Linux Terminal Server Project"
