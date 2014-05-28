#!/usr/bin/env python
# -*- coding: utf-8 -*-

import atexit
import codecs
import os
import re
import shutil
import subprocess
from datetime import datetime
from posixpath import join as urljoin

import click
import jinja2
import yaml
from markdown import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from slugify import slugify


# ========================================================================
# utils
# ========================================================================

class _HtmlListFormatter(HtmlFormatter):

  def wrap(self, source, outfile):
    return self._wrap_div(self._wrap_pre(self._wrap_list(source)))

  def _wrap_list(self, source):
    yield (0, '<ol>')
    for (i, t) in source:
      if i == 1:
        t = '<li><div class="line">{0}</div></li>'.format(t)
      yield (i, t)
    yield (0, '</ol>')


def _highlight_match(matchobj):

  lexer = get_lexer_by_name(matchobj.group('syntax').strip().lower(),
                            stripall=True)
  if config['code_line_numbers']:
    formatter = _HtmlListFormatter()
  else:
    formatter = HtmlFormatter()
  return highlight(matchobj.group('code'), lexer, formatter)


# ========================================================================
# commands
# ========================================================================

@click.group()
def cli():
  pass


@cli.command()
def new():
  """Create a new post or page."""

  date = datetime.now()
  page_type = click.prompt('Create new post/page', type=click.Choice(['post',
                           'page']), default='post')
  page_attributes['title'] = click.prompt('Title', default='New ' + page_type)
  page_attributes['date'] = date.strftime(config['internal_date_format'])

  # set default page attribute values

  page_attributes['template'] = config['default_template']
  page_attributes['categories'] = ''
  if page_type == 'post':

    # i.e. "2014-05-10-post-title.md"

    file_name = date.strftime(config['post_prefix_format']) \
      + slugify(page_attributes['title']) + '.md'
  else:

    # i.e. "page-title.md"

    file_name = slugify(page_attributes['title']) + '.md'
  file_path = os.path.join(config['src_dir'], file_name)
  if os.path.isfile(file_path):
    click.echo('A page with the same name already exists.')
  else:
    with open(file_path, 'w') as f:
      f.write(config['delimiter'])
      f.write(yaml.dump(page_attributes, default_flow_style=False))
      f.write(config['delimiter'])
      f.write('\n')


@cli.command()
def mini():
  """Minify css and js."""

  click.echo('Processing css and js files')
  subprocess.call(['crammit', '-c', 'config/config.yaml'])


@cli.command()
@click.option('--prod', is_flag=True)
def build(prod):
  """Build pages."""

  # use "/" as site_root when running stuff locally

  if not prod:
    config['site_root'] = '/'
  click.echo('Building pages')
  posts = []
  pages = []
  categories = set()
  link_prefix_len = len(config['post_prefix_format'])
  code_block_regex = \
    re.compile(r'//code (?P<syntax>[a-zA-Z]+)(?P<code>.*?)//code', re.DOTALL)

  # read the files from the src directory

  for file_name in os.listdir(config['src_dir']):
    file_path = os.path.join(config['src_dir'], file_name)
    if os.path.isfile(file_path):
      with codecs.open(file_path, mode='r', encoding='utf-8') as f:
        data = f.read().split(config['delimiter'])

        # load the page attributes from the file

        page_attributes = yaml.load(data[1])

        # add syntax highlighting and render as html

        page_attributes['content'] = markdown(re.sub(code_block_regex,
              _highlight_match, data[2]), output_format='html5')

        # eliminate any code blocks from the excerpt (they may cause problems)
        # and render as html

        page_attributes['excerpt'] = markdown(re.sub(code_block_regex,
              '`here-be-code`', data[2])[:config['excerpt_length'
              ]].rpartition(' ')[0] + '...', output_format='html5')

      # convert date from string to datetime instance

      page_attributes['date'] = datetime.strptime(page_attributes['date'],
            config['internal_date_format'])

      # create a list of {'name': '...', 'link': '...'} for each category
      # found in the page

      page_attributes['categories'] = [{'name': x.strip().lower(),
                                       'link': urljoin(config['site_root'],
                                       'category', slugify(x.strip())) + '/'}
                                       for x in page_attributes['categories'
                                       ].split(',') if x.strip() != '']

      # add the found categories to the set

      [categories.add(x['name']) for x in page_attributes['categories']]

      # set additional page attributes

      page_attributes['site_root'] = config['site_root']
      page_attributes['file_name'] = file_name.replace('.md', '')
      page_attributes['link'] = urljoin(config['site_root'],
            file_name.replace('.md', '')) + '/'

      # figure out whether the file should be rendered as a post or page

      try:

        # files that start with "post_prefix_format" are posts

        datetime.strptime(file_name[:link_prefix_len + 2],
                          config['post_prefix_format'])
        posts.append(page_attributes)
      except ValueError:

        # the rest of them are pages

        pages.append(page_attributes)

  # sort posts from newest to oldest

  posts = sorted(posts, key=lambda x: x['date'], reverse=True)
  categories = list(categories)

  # add "Previous Post" and "Next Post" links to posts

  if config['prev_next_links']:
    for i in range(0, len(posts)):
      if i + 1 <= len(posts) - 1:
        posts[i]['prev_post'] = urljoin(config['site_root'], posts[i
              + 1]['file_name']) + '/'
      if i - 1 >= 0:
        posts[i]['next_post'] = urljoin(config['site_root'], posts[i
              - 1]['file_name']) + '/'
  environment = \
    jinja2.Environment(loader=jinja2.FileSystemLoader(config['template_dir']))

  # write the html files to disk

  for page in posts + pages:
    dir_path = os.path.join(config['dist_dir'], page['file_name'])
    if not os.path.exists(dir_path):
      os.makedirs(dir_path)
    template = environment.get_template(page['template'])
    render = template.render(page)
    file_path = os.path.join(dir_path, 'index.html')
    with codecs.open(file_path, mode='w', encoding='utf-8') as f:
      f.write(render)

  # write a page for each of the categories

  template = environment.get_template(config['category_template'])
  for category in categories:
    posts_in_category = [x for x in posts if category in [y['name'] for y in
                         x['categories']]]
    dir_path = os.path.join(config['dist_dir'], 'category', slugify(category))
    if not os.path.exists(dir_path):
      os.makedirs(dir_path)
    render = template.render({'category': category,
                             'posts': posts_in_category,
                             'site_root': config['site_root']})
    file_path = os.path.join(dir_path, 'index.html')
    with codecs.open(file_path, mode='w', encoding='utf-8') as f:
      f.write(render)

  # and last but not least write a html file to serve as a home page

  template = environment.get_template(config['home_template'])
  render = template.render({'posts': posts, 'site_root': config['site_root']})
  file_path = os.path.join(config['dist_dir'], 'index.html')
  with codecs.open(file_path, mode='w', encoding='utf-8') as f:
    f.write(render)


@cli.command()
@click.pass_context
def update(context):
  """Minify + build."""

  context.invoke(mini)
  context.invoke(build, False)


@cli.command()
def runserver():
  """Run local server."""

  os.chdir(config['dist_dir'])
  process = subprocess.call(['python', '-m', 'SimpleHTTPServer', config['port'
                            ]])

  # kill the spawned child process (i.e. the http server) on exit

  atexit.register(process.terminate)


@cli.command()
@click.option('--all', is_flag=True)
def reset(all):
  """Reset site by removing all files."""

  click.confirm('Reset site and remove all files?', abort=True)
  if os.path.isdir(config['dist_dir']):
    shutil.rmtree(config['dist_dir'])
  if all:
    click.confirm('Remove source files as well?', abort=True)
    for file_name in os.listdir(config['src_dir']):
      file_path = os.path.join(config['src_dir'], file_name)
      if os.path.isfile(file_path):
        os.remove(file_path)
      elif os.path.isdir(file_path):
        shutil.rmtree(file_path)


if __name__ == '__main__':
  config_path = os.path.join('config', 'config.yaml')
  with open(config_path, 'r') as config_file:
    config = yaml.load(config_file)
  page_attributes_path = os.path.join('config', 'page_attributes.yaml')
  with open(page_attributes_path, 'r') as page_attributes_file:
    page_attributes = yaml.load(page_attributes_file)
  cli()