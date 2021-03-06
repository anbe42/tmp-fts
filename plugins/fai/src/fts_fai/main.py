# -*- coding: utf-8 -*-
import ldap
import ldap.filter
import os
import syslog
import re
from fts.ldap_utils import LDAPHandler
from fts.bootplugin import BootPlugin


class FAIBoot(BootPlugin):

    def __init__(self):
        super(FAIBoot, self).__init__()

        self.ldap = LDAPHandler.get_instance()
        self.nfs_root= self.config.get('fai.nfs-root', '/srv/nfsroot')
        self.fai_flags= self.config.get('fai.flags', 'verbose,sshd,syslogd,createvt,reboot')
        self.union= self.config.get('fai.union', 'unionfs')
        self.default_init= self.config.get('fai.default-init', 'fallback')
        self.tftp_root = os.path.dirname(self.config.get('tftp.path', '/tftpboot/pxelinux.cfg'))

    def getBootParams(self, address):
        #syslog.syslog(syslog.LOG_DEBUG, "Searching for {address}".format(address=address))
        with self.ldap.get_handle() as conn:
            res = conn.search_s(
                self.ldap.get_base(),
                ldap.SCOPE_SUBTREE,
                ldap.filter.filter_format("(&(macAddress=%s)(objectClass=FAIobject))", [address]),
                ['FAIstate', 'gotoBootKernel', 'gotoKernelParameters', 'gotoLdapServer', 'cn', 'ipHostNumber'])

            if res is not None:
                count = len(res)
                if count > 1:
                    syslog.syslog("[fai] ignoring %s - LDAP search is not unique (%d entries match)" % (address, res.count()))
                    return None

                if count == 1:
                    dn, attributes = res[0]
                    hostname = attributes.get('cn', [''])[0]
                    status = attributes.get('FAIstate', [''])[0]
                    if not status:
                        if self.default_init == 'fallback':
                            syslog.syslog(syslog.LOG_DEBUG, "[fai] No FAI Status for {hostname} - continue PXE boot".format(hostname=hostname))
                            return None
                        else:
                            status = self.default_init

                    syslog.syslog(syslog.LOG_DEBUG, "[fai] Found {hostname}, FAI Status is '{status}'".format(hostname=hostname, status=status))
                    kernel = attributes.get('gotoBootKernel', [''])[0]
                    ldap_server = attributes.get('gotoLdapServer', [''])[0]
                    cmdline = attributes.get('gotoKernelParameters', [''])[0]

                    if not kernel or not ldap_server or not cmdline:
                        # Check group membership
                        member_res = conn.search_s(
                            self.ldap.get_base(),
                            ldap.SCOPE_SUBTREE,
                            ldap.filter.filter_format("(&(member=%s)(objectClass=gosaGroupOfNames)(gosaGroupObjects=[W]))", [dn]),
                            ['FAIstate', 'gotoBootKernel', 'gotoKernelParameters', 'gotoLdapServer', 'cn', 'ipHostNumber'])
                        if member_res is not None:
                            group_count = len(member_res)
                            if group_count > 1:
                                syslog.syslog(syslog.LOG_ERR, "[fai] Found more than one group for host {hostname}!")
                                return None

                            if group_count == 1:
                                group_dn, group_attributes = member_res[0]

                                if not kernel:
                                    kernel = group_attributes.get('gotoBootKernel', [''])[0]

                                if not ldap_server:
                                    ldap_server = group_attributes.get('gotoLdapServer', [''])[0]

                                if not cmdline:
                                    cmdline = group_attributes.get('gotoKernelParameters', [''])[0]

                            if group_count == 0:
                                syslog.syslog(syslog.LOG_INFO, "[fai] {hostname} - no group membership found - aborting".format(hostname=hostname))

                    if not kernel or not ldap_server:
                        line = "[fai] {hostname} - missing attribute(s) -".format(hostname=hostname)
                        if not kernel:
                            line = line + " gotoBootKernel"
                        if not ldap_server:
                            line = line + " gotoLdapServer"
                        syslog.syslog(syslog.LOG_ERR, line)
                        return None

                    # Strip ldap parameter and all multiple and trailing spaces
                    cmdline = re.sub(r'ldap(=[^\s]*[\s]*|[\s]*$|\s+)', '', cmdline)
                    cmdline = re.sub(r'\s[\s]+', '', cmdline.strip())

                    # Get kernel and initrd from TFTP root
                    kernel='vmlinuz-install'
                    initrd='initrd.img-install'

                    # - guess filename for kernel
                    if not os.access(self.tftp_root + os.sep + kernel, os.F_OK):
                        syslog.syslog(syslog.LOG_ERR, "[fai] {hostname} - specified kernel {kernel} does not exist!".format(hostname=hostname, kernel=kernel))
                        return None

                    # - try to find the initrd
                    path = self.tftp_root + os.sep + initrd
                    if os.access(path, os.F_OK):
                        cmdline = cmdline + " initrd={initrd}".format(initrd=initrd)
                        cmdline = cmdline.strip()

                    # Add NFS options
                    cmdline = cmdline + " nfsroot=" + self.nfs_root
                    cmdline = cmdline.strip()

                    # Add FAI options
                    if status in ['install', 'install-init']:
                        cmdline = cmdline + " FAI_ACTION=install FAI_FLAGS={fai_flags} ip=dhcp".format(fai_flags=self.fai_flags) \
                                 + " devfs=nomount root=/dev/nfs boot=live union={union}".format(union=self.union)
                    elif status.startswith('error:') or status.startswith('installing:'):
                        faierror = ""
                        if status.startswith("installing:"):
                            faierror = "inst-"
                        faierror = faierror + status.split(":", 1)[1]
                        cmdline = cmdline + " FAI_ACTION=install FAI_FLAGS={fai_flags} ip=dhcp".format(fai_flags=self.fai_flags) \
                                + " devfs=nomount root=/dev/nfs boot=live union={union} faierror:{faierror}".format(union=self.union, faierror=faierror)
                    elif status in ['softupdate', 'localboot']:
                        kernel = 'localboot'

                    elif status == 'sysinfo':
                        sysflags = ','.join(filter(lambda x: x.strip() != "reboot", self.fai_flags.split(',')))
                        cmdline = cmdline + " FAI_ACTION=sysinfo FAI_FLAGS={fai_flags} ip=dhcp".format(fai_flags=sysflags) \
                                 + " devfs=nomount root=/dev/nfs boot=live union={union}".format(union=self.union)
                    else:
                        # Unknown status
                        syslog.syslog(syslog.LOG_ERR, "[fai] {hostname} - unknown FAIstate: {status}".format(hostname=hostname, status=status))
                        return None

                    return self.make_pxe_entry(kernel, cmdline, label="FAI - powered by FTS")

        return None

    def getInfo(self):
        return "FAI - Fully Automatic Installation"
