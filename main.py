import sys
import bz2
from dataclasses import dataclass
import typing

import xml.etree.ElementTree as ET
import mwparserfromhell as mwp

from tkinter import font
from tkinter import *
from tkinter.ttk import *

@dataclass
class IndexEntry:
	file_offset: int
	page_id: int
	article_name: str

def get_file_size(f: typing.TextIO) -> int:
	""" Gets file size without, restores the file position. """
	restore = f.tell()
	f.seek(0, 2)
	ret = f.tell()
	f.seek(restore)
	return ret

def split_index_parts(line: str) -> typing.Tuple[str, str]:
	""" Splits a string by the first ':' character.
	The wikipedia index file is a file with lines formatted like this:
	aaaaa:bbbbb:About C:\System32
	Here the file offset is aaaaa, the page id is bbbbb, and the title is
	C:\System32, note that the title can contain a colon.

	this function takes the example line and returns this:
	('aaaaa', 'bbbbb:About C:\System32')
	So we extracted the first item, the second tuple element is the rest of the
	string. Now we can directly put the second element into this function to
	extract the last two items.
	"""
	end = line.find(':')
	return (line[0 : end], line[end + 1 :])

def parse_index_line(file_offset_page_id_article_name_nl: str) -> IndexEntry:
	""" Parses a line from the wikipedia index file.
	The passed string is expected to have a trailing newline
	"""
	file_offset,page_id_article_name_nl = split_index_parts(file_offset_page_id_article_name_nl)
	page_id,article_name_nl             = split_index_parts(page_id_article_name_nl)
	return IndexEntry(int(file_offset), int(page_id), article_name_nl[:-1])


def contains_substr_predicate(text: str):
	""" Returns true for IndexEntries who's article name contains 'text'
	This function is primarily intended for use in load_index, example usage:

	load_index(index_file, contains_substr_predicate('C++'))

	this will return all article index entries who's article name contains C++.
	"""
	def ret(entry: IndexEntry):
		return text in entry.article_name

	return ret

def exact_match_smart_predicate(text: str):
	""" Returns true for IndexEntries who's article name is 'text'.
	The comparison is case insensitive if the 'text' is only lower case
	characters, else it's a case sensitive search. This function is primarily
	intended for use in load_index.
	"""
	def ci_ret(entry: IndexEntry):
		return text.lower() == entry.article_name.lower()

	def cs_ret(entry: IndexEntry):
		return text == entry.article_name

	if text == text.lower():
		return ci_ret
	else:
		return cs_ret

class WikiDb():
	def __init__(self, wiki_file_name: str, index_file_name: str):
		self.index_file = open(index_file_name, 'r')
		self.wiki_file = open(wiki_file_name, 'rb')

		self.offset_map = self.__load_offset_map()

	def __load_offset_map(self):
		""" Returns a dictionary that converts a start_offset into an end_offset
		this modifies the index_file's file position
		"""
		self.index_file.seek(0)

		offset_map = {}
		previous = -1

		for index_entry_text in self.index_file:
			file_offset_str,_ = split_index_parts(index_entry_text)
			file_offset = int(file_offset_str)

			if previous == -1:
				previous = file_offset

			if file_offset != previous:
				offset_map[previous] = file_offset
				previous = file_offset

		# The index file only lists the start offset of each article chunk.
		# Since the start of one chunk is the end of another, we can use that
		# fact to get the begin/end of every chunk except for the last chunk.
		# For the last chunk's end we read the wikipedia articles bzip2 file
		# size.
		last_offset = get_file_size(self.wiki_file)
		offset_map[previous] = last_offset

		return offset_map

	def load_index(self, predicate: typing.Callable[[IndexEntry], bool]) -> typing.List[IndexEntry]:
		""" Loads IndexEntry entries from index_file
		Changes the index_file's file position.

		The index file is too big, so loading the full file is not a good idea,
		instead this only returns entries that return true for the predicate.
		"""
		self.index_file.seek(0)
		entries = []
		for index_entry_text in self.index_file:
			entry = parse_index_line(index_entry_text)
			if predicate(entry):
				entries.append(entry)

		return entries

	def load_index_single(self, predicate: typing.Callable[[IndexEntry], bool]) -> typing.List[IndexEntry]:
		""" Loads IndexEntry entries from index_file
		Changes the index_file's file position.
		"""
		self.index_file.seek(0)
		for index_entry_text in self.index_file:
			entry = parse_index_line(index_entry_text)
			if predicate(entry):
				return entry

		return None

	def __load_chunk(self, entry):
		begin = entry.file_offset
		end = self.offset_map[begin]
		chunk_size = end - begin

		self.wiki_file.seek(begin)
		decompressor = bz2.BZ2Decompressor()
		data = decompressor.decompress(self.wiki_file.read(chunk_size))
		text = data.decode('utf-8')
		return text

	def load_article(self, entry):
		chunk = self.__load_chunk(entry)

		# Xml must have a single root, a single multistream contains multiple pages, so
		# we have to add a root element.
		root = ET.fromstring('<root>' + chunk + '</root>')

		def is_match(page):
			return int(page.find('id').text) == entry.page_id

		page = next(filter(is_match, root))
		page_contents = page.find('revision/text').text;
		parsed = mwp.parse(page_contents)

		return parsed

class WikicodeToTkText:
	def __init__(self, master, make_wikilink_binding):
		self.text = Text(master)
		self.make_wikilink_binding = make_wikilink_binding

	def parse(self, wikicode):
		self.text.tag_config('heading1', font = font.Font(size = 40))
		self.text.tag_config('heading2', font = font.Font(size = 30))
		self.text.tag_config('heading3', font = font.Font(size = 22))
		self.text.tag_config('heading4', font = font.Font(size = 16))
		self.text.tag_config('heading5', font = font.Font(size = 12))
		self.text.tag_config('heading6', font = font.Font(size = 10))

		self.__handle_wikicode(wikicode)

		# disable editing text
		def on_press(e):
			return None

		self.text.bind("<Key>", lambda e: "break")
		self.text.bind("<Button-1>", on_press)

		self.text.pack(expand = 1, fill = BOTH)

		return self.text

	def __handle_wikicode(self, wikicodeobj):
		for node in wikicodeobj.nodes:
			if isinstance(node, mwp.nodes.Text):
				self.__handle_text(node)

			elif isinstance(node, mwp.nodes.Wikilink):
				self.__handle_wikilink(node)

			elif isinstance(node, mwp.nodes.Heading):
				self.__handle_heading(node)

			elif isinstance(node, mwp.nodes.Tag):
				self.__handle_tag(node)

			elif isinstance(node, mwp.nodes.Template):
				self.__handle_template(node)

			elif isinstance(node, mwp.nodes.ExternalLink):
				self.__handle_external_link(node)

			else:
				print('Could not print type ' + str(type(node)))

	def __handle_text(self, textobj):
		self.text.insert(END, textobj.value)

	def __handle_wikilink(self, wikilinkobj):
		link_text = str(wikilinkobj.text or wikilinkobj.title)
		title = str(wikilinkobj.title)

		# Tcl/tk doesn't seems to like certain characters in the tag name
		linktagname = title.replace(' ', '#space#').replace('"', '#quote#')

		# Does this link not have a tag configured yet?
		if linktagname not in self.text.tag_names():
			self.text.tag_config(linktagname, foreground = 'blue')
			self.text.tag_bind(linktagname, '<Button-1>', self.make_wikilink_binding(title))

		self.text.insert(END, link_text, linktagname)

	def __handle_heading(self, headingobj):
		self.text.insert(END, str(headingobj.title), 'heading' + str(headingobj.level))

	def __handle_tag(self, tagobj):
		self.text.insert(END, str(tagobj))

	def __handle_template(self, templateobj):
		print(str(templateobj.name) + '  ' + str(templateobj.name.matches('Infoboc')))
		#print(templateobj.params)
		self.text.insert(END, str(templateobj))

	def __handle_external_link(self, externallinkobj):
		self.text.insert(END, str(externallinkobj))

class Window(Frame):
	def __init__(self, master = None):
		self.page_text = None
		super().__init__(master)
		self.pack(expand = 1, fill = BOTH)

		wiki_file_name = sys.argv[1]
		index_file_name = sys.argv[2]

		self.wikidb = WikiDb(wiki_file_name, index_file_name)

		entry = self.wikidb.load_index_single(exact_match_smart_predicate('C++'))
		parsed = self.wikidb.load_article(entry)
		self.set_page(parsed)

	def make_link_binding(self, link):
		def ret(e):
			print(link)
			index = self.wikidb.load_index_single(exact_match_smart_predicate(link))
			parsed = self.wikidb.load_article(index)
			self.set_page(parsed)

		return ret

	def set_page(self, article):
		if self.page_text:
			self.page_text.pack_forget()

		parser = WikicodeToTkText(self, self.make_link_binding)
		self.page_text = parser.parse(article)

root = Tk()
root.rowconfigure(0, weight=1)
root.columnconfigure(0, weight=1)

window = Window(root)
root.mainloop()
