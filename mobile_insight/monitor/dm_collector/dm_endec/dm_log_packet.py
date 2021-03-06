# -*- coding: utf-8 -*-
"""
dm_log_packet.py
Defines DMLogPacket class.

Author: Jiayao Li
"""

__all__ = ["DMLogPacket", "FormatError"]

import binascii
from datetime import *
import json
import struct
#import xml.etree.ElementTree as ET
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

try:
    from utils import *
except ImportError as e:
    # TODO: WTF can I do to remove this dependence ..?
    def static_var(varname, value):
        def decorate(func):
            setattr(func, varname, value)
            return func
        return decorate

from ws_dissector import *

import itertools


def range(stop): return iter(itertools.count().next, stop)


class SuperEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return str(obj)
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


class FormatError(RuntimeError):
    """
    Error in decoding messages.
    """
    pass


class DMLogPacket:
    """
    DM log packet decoder.

    A log packet contains a header that specifies the packet type and
    timestamp, and a payload field that store useful information of a
    phone. This class will decode both the header and payload fields.

    This class depends on Wireshark to decode some 3GPP standardized
    messages.
    """

    _init_called = False

    def __init__(self, decoded_list):
        """
        Initialize a log packet.

        :param decoded_list: output of *dm_collector_c* library
        :type decoded_list: list
        """
        cls = self.__class__

        self._decoded_list = cls._preparse_internal_list(decoded_list)

    @classmethod
    @static_var("wcdma_sib_types", {0: "RRC_MIB",
                                    1: "RRC_SIB1",
                                    2: "RRC_SIB2",
                                    3: "RRC_SIB3",
                                    7: "RRC_SIB7",
                                    12: "RRC_SIB12",
                                    27: "RRC_SB1",
                                    31: "RRC_SIB19",
                                    })
    def _preparse_internal_list(cls, decoded_list):
        lst = []
        try:
            # for i in range(len(decoded_list)):
            i = 0
            while i < len(decoded_list):
                field_name, val, type_str = decoded_list[i]
                if type_str.startswith("raw_msg/"):
                    msg_type = type_str[len("raw_msg/"):]
                    decoded = cls._decode_msg(msg_type, val)
                    xmls = [decoded, ]

                    if msg_type == "RRC_DL_BCCH_BCH":
                        sib_types = cls._preparse_internal_list.wcdma_sib_types
                        try:
                            # xml = ET.fromstring(decoded)
                            xml = ET.XML(decoded)
                        except Exception as e:
                            print "Unsupported RRC_DL_BCCH_BCH"
                            xx = cls._wrap_decoded_xml(xmls)
                            lst.append(("Unsupported", xx, "msg"))
                            return lst

                        sibs = xml.findall(
                            ".//field[@name='rrc.CompleteSIBshort_element']")
                        if sibs:
                            # deal with a list of complete SIBs
                            for complete_sib in sibs:
                                field = complete_sib.find(
                                    "field[@name='rrc.sib_Type']")
                                sib_id = int(field.get("show"))
                                sib_name = field.get("showname")
                                field = complete_sib.find(
                                    "field[@name='rrc.sib_Data_variable']")
                                sib_msg = binascii.a2b_hex(field.get("value"))
                                if sib_id in sib_types:
                                    decoded = cls._decode_msg(
                                        sib_types[sib_id], sib_msg)
                                    xmls.append(decoded)
                                    # print sib_types[sib_id]
                                else:
                                    print "Unknown RRC SIB Type: %d" % sib_id
                        else:
                            # deal with a segmented SIB
                            sib_segment = xml.find(
                                ".//field[@name='rrc.firstSegment_element']")
                            if sib_segment is None:
                                sib_segment = xml.find(
                                    ".//field[@name='rrc.subsequentSegment_element']")
                            if sib_segment is None:
                                sib_segment = xml.find(
                                    ".//field[@name='rrc.lastSegmentShort_element']")
                            if sib_segment is not None:
                                field = sib_segment.find(
                                    "field[@name='rrc.sib_Type']")
                                sib_id = int(field.get("show"))
                                # Zengwen: need to use log it back
                                # print "RRC SIB Segment(type: %d) not handled"
                                # % sib_id
                    xx = cls._wrap_decoded_xml(xmls)
                    lst.append((field_name, xx, "msg"))
                else:
                    lst.append(decoded_list[i])
                i = i + 1
            return lst

        except Exception as e:
            print len(decoded_list)
            print decoded_list
            i = 0
            while i < len(decoded_list):
                print i
                print decoded_list[i]
                i += 1
            import traceback
            raise RuntimeError(str(traceback.format_exc()))

    @classmethod
    def _parse_internal_list(cls, out_type, decoded_list):
        """
        Parse the internal list to create different types of output.

        :param out_type: can be "dict", "list", "xml/dict" or "xml/list"
        :type out_type: string

        :param decoded_list: output of dm_collector_c library
        :type decoded_list: list
        """

        if out_type == "dict":
            output_d = dict()
        elif out_type == "list":
            output_lst = []
        elif out_type.startswith("xml/"):
            tag_name = out_type[len("xml/"):]
            output_xml = ET.Element(tag_name)

        # for field_name, val, type_str in decoded_list:
        i = 0
        while i < len(decoded_list):
            # print "debug decoded_list: ",str(decoded_list[i])
            field_name, val, type_str = decoded_list[i]

            if not type_str:    # default type
                xx = val
            elif type_str == "msg":
                xx = val
            elif type_str == "dict":
                if out_type.startswith("xml/"):
                    xx = cls._parse_internal_list("xml/dict", val)
                else:
                    xx = cls._parse_internal_list("dict", val)
            elif type_str == "list":
                if out_type.startswith("xml/"):
                    xx = cls._parse_internal_list("xml/list", val)
                else:
                    xx = cls._parse_internal_list("list", val)

            if out_type == "dict":
                output_d[field_name] = xx
            elif out_type == "list":
                output_lst.append(xx)
            elif out_type.startswith("xml/"):
                # Create tag
                if out_type == "xml/list":
                    sub_tag = ET.SubElement(output_xml, "item")
                elif out_type == "xml/dict":
                    sub_tag = ET.SubElement(
                        output_xml, "pair", {
                            "key": field_name})

                if not type_str:
                    xx = str(xx)
                    sub_tag.text = xx
                else:
                    if type_str == "msg":
                        # xx = ET.fromstring(xx)
                        xx = ET.XML(xx)
                        sub_tag.set("type", "list")
                    else:
                        sub_tag.set("type", type_str)
                    sub_tag.append(xx)

            i = i + 1

        if out_type == "dict":
            return output_d
        elif out_type == "list":
            return tuple(output_lst)
        elif out_type.startswith("xml/"):
            return output_xml

    def decode(self):
        """
        Decode a DM log packet.

        :returns: a Python dict object that looks like::

            {
                "type_id": "LTE_RRC_OTA_Packet",
                "timestamp": datetime.datetime(......),
                "Pkt Version": 2,
                "RRC Release Number": 9,
                # other fields ...
                "Msg": \"\"\"
                    <msg>
                        <packet>...</packet>
                        <packet>...</packet>
                        <packet>...</packet>
                    </msg>
                    \"\"\",
            }

        :raises FormatError: this message has an unknown type
        """
        cls = self.__class__

        d = cls._parse_internal_list("dict", self._decoded_list)
        return d

    def decode_xml(self):
        """
        Decode the message and convert to a standard XML document.

        :returns: a string that contains the converted XML document.
        """
        cls = self.__class__

        xml = cls._parse_internal_list("xml/dict", self._decoded_list)
        # Zengwen: what about this name?
        xml.tag = "dm_log_packet"
        return ET.tostring(xml)

    def decode_json(self):
        """
        Decode the message and convert to a standard JSON dictionary.

        :returns: a string that contains the converted JSON document.
        """
        cls = self.__class__

        d = self.decode()

        try:
            import xmltodict
            if "Msg" in d:
                d["Msg"] = xmltodict.parse(d["Msg"])
        except ImportError:
            pass
        return json.dumps(d, cls=SuperEncoder)

    @classmethod
    def init(cls, prefs):
        """
        Configure the DMLogPacket class with user preferences.

        This method should be called before any actual decoding.

        :param prefs: a dict storing the preferences
        :type prefs: dict
        """
        if cls._init_called:
            return
        WSDissector.init_proc(prefs.get("ws_dissect_executable_path", None),
                              prefs.get("libwireshark_path", None))
        cls._init_called = True

    @classmethod
    def _search_result(cls, result, target):
        if isinstance(target, str):
            target = [target]
        assert isinstance(target, (list, tuple))
        assert len(target) > 0

        ret = [None for i in range(len(target))]
        for name, decoded in result:
            i = 0
            for t in target:
                if name == t:
                    ret[i] = decoded
                i += 1

        assert all([x is not None for x in ret])
        if len(target) == 1:
            return ret[0]
        else:
            return tuple(ret)

    @classmethod
    def _decode_msg(cls, msg_type, b):
        """
        Decode standard message using WSDissector.
        """
        assert cls._init_called

        s = WSDissector.decode_msg(msg_type, b)
        return s

    @classmethod
    def _wrap_decoded_xml(cls, xmls):
        """
        :returns: an XML string that looks like::

            <msg>
                <packet>...</packet>
                <packet>...</packet>
                <packet>...</packet>
            </msg>
        """
        if isinstance(xmls, str):
            xmls = [xmls]
        if None in xmls:
            return "<msg>\n</msg>\n"
        assert isinstance(xmls, (list, tuple))
        return "<msg>\n" + "".join(xmls) + "</msg>\n"
