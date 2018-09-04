import re
from bs4 import NavigableString
from .search import Param, MultiParam, UIntParam, Searchable


class Filter(MultiParam):
    """
    A multi-valued filter parameter represented as a set. The set of allowed values is
    represented as a dict of {title: internal val}.
    """

    def __init__(self, head, cell, default=None):
        """
        :param    head: The head elm from the filter table
        :param    cell: The cell elm from the filter table
        :param default: Set of default values for this filter, or None
        """
        select = cell.find(name='select', recursive=False)
        self.options = {o.text.strip(): o.attrs['value']
                        for o in select.find_all(name='option', recursive=False)}
        self.option_titles = set(self.options.keys())
        super().__init__(title=head, name=select.attrs['name'], default=default)
        # todo - deal with min/max selection

    def validate(self, value):
        if value is None:
            return True
        return isinstance(value, set) and not (value - self.option_titles)

    def update_qps(self, qps, value=None):
        if value is None:
            value = self.default
        if value:
            qps[self.name] = {self.options[v] for v in value}


class SortParam(Param):
    """
    Search parameter controlling result order. Value is of the form (t, dirn) where t is any of the
    column titles, and dirn is either True (ascending) or False (descending).
    """

    rex_sort = re.compile(r'sort\(([0-9\-]+)\);')

    def __init__(self, doc, default=None):
        """
        :param     doc: BeautifulSoup doc of the filter page
        :param default: None, or ('col', bool)
        """
        super().__init__(title='Column Sort', name='ColumnSort', default=default)

        # Dict of {title: code}
        self.by = {}

        table = doc.find(name='table', id='productTable')
        heads = Category.get_heads(table)
        cells = table.select('thead#tblhead > tr:nth-of-type(2) > td')

        for head, cell in zip(heads, cells):
            # Take the first (ascending) button only.
            button = cell.find(name='button', class_='ps-sortButtons')
            if not button:
                continue
            img = button.find(name='img', class_='nonsorted')
            _, _, dirn = img.attrs['src'].rpartition('/')
            assert(dirn.startswith('up'))

            code = int(SortParam.rex_sort.search(button.attrs['onclick'])[1])
            assert(code > 0)
            self.by[head] = code

    def validate(self, value):
        if value is None:
            return True
        if not isinstance(value, tuple) or len(value) != 2:
            return False
        by, dirn = value
        return by in self.by and isinstance(dirn, bool)

    def update_qps(self, qps, value=None):
        if value is None:
            value = self.default
        title, dirn = value
        code = self.by[title]
        if not dirn:
            code = -code
        qps[self.name] = code


class Category(Searchable):
    rex_count = re.compile(r'\((\d+)')

    def __init__(self, session, group, elm):
        a = elm.find(name='a', recursive=False)
        self.short_title = a.text
        self.group = group
        super().__init__(session=session, path=a.attrs['href'],
                         title='%s/%s' % (group.title, self.short_title))

        for child in elm.children:
            if isinstance(child, NavigableString):
                match = Category.rex_count.search(child)
                if match:
                    self.size = int(match[1])
                    break

    def _get_addl_params(self):
        print('Initializing search for category %s...' % self.title)

        doc = self.session.get_doc(self.path + '?pageSize=0')
        table = doc.find(name='table', class_='filters-group')
        headers = table.select('tr#appliedFilterHeaderRow > th')
        cells = table.select('tr#appliedFilterOptions > td')

        filters = [UIntParam('Page Size', 'pageSize', 25),
                   SortParam(doc, default=('Unit Price', 'Ascending'))]
        for head, cell in zip(headers, cells):
            title = head.text
            if title == 'Part Status':
                default = {'Active'}
            else:
                default = None
            filters.append(Filter(title, cell, default))
        return filters

    @staticmethod
    def get_heads(table):
        for th in table.select('thead#tblhead > tr:nth-of-type(1) > th'):
            cls = th.attrs['class'][0]
            if cls == 'th-datasheet':
                head = 'Datasheet'  # this is shown as an image, no text
            elif 'th-unitPrice' in cls:
                head = 'Unit Price'  # leave out the whitespace and currency
            else:
                head = th.text.strip()
            yield head

    @staticmethod
    def _get_parts(table, heads):
        for tr in table.select('tbody#lnkPart > tr'):
            part = {}
            cells = tr.find_all(name='td', recursive=False)
            for head, td in zip(heads, cells):
                cls = td.attrs['class'][0]
                if cls == 'tr-datasheet':
                    col = td.select('a.lnkDatasheet')[0].attrs.get('href')
                elif cls == 'tr-image':
                    img = td.find('img')
                    if img.attrs.get('alt') == 'Photo Not Available':
                        col = None
                    else:
                        col = img.attrs.get('zoomimg')
                else:
                    col = td.text
                if col and cls != 'tr-compareParts':
                    part[head] = col.strip()
            yield part

    def search(self, param_values):
        # todo - pagination generator
        doc = super().search(param_values)
        table = doc.select('table#productTable')[0]
        heads = tuple(Category.get_heads(table))
        parts = tuple(Category._get_parts(table, heads))
        return parts
