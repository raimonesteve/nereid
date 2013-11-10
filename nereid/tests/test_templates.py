# -*- coding: utf-8 -*-
#This file is part of Tryton & Nereid. The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
import os
import unittest
import pickle

import pycountry
import trytond.tests.test_tryton
from trytond.transaction import Transaction
from trytond.backend.sqlite.database import Database as SQLiteDatabase  # noqa
from trytond.tests.test_tryton import POOL, USER, DB_NAME, CONTEXT
from nereid import render_template, LazyRenderer
from nereid.testing import NereidTestCase, NereidTestApp
from nereid.sessions import Session
from nereid.contrib.locale import Babel
from werkzeug.contrib.sessions import FilesystemSessionStore


class BaseTestCase(NereidTestCase):

    def setUp(self):
        trytond.tests.test_tryton.install_module('nereid')

        self.nereid_website_obj = POOL.get('nereid.website')
        self.nereid_website_locale_obj = POOL.get('nereid.website.locale')
        self.nereid_user_obj = POOL.get('nereid.user')
        self.url_map_obj = POOL.get('nereid.url_map')
        self.company_obj = POOL.get('company.company')
        self.currency_obj = POOL.get('currency.currency')
        self.language_obj = POOL.get('ir.lang')
        self.country_obj = POOL.get('country.country')
        self.subdivision_obj = POOL.get('country.subdivision')
        self.party_obj = POOL.get('party.party')

    def create_countries(self, count=5):
        """
        Create some sample countries and subdivisions
        """
        for country in list(pycountry.countries)[0:count]:
            country_id, = self.country_obj.create([{
                'name': country.name,
                'code': country.alpha2,
            }])
            try:
                divisions = pycountry.subdivisions.get(
                    country_code=country.alpha2
                )
            except KeyError:
                pass
            else:
                self.subdivision_obj.create([{
                    'country': country_id,
                    'name': subdivision.name,
                    'code': subdivision.code,
                    'type': subdivision.type.lower(),
                } for subdivision in list(divisions)[0:count]])

    def setup_defaults(self):
        """
        Setup the defaults
        """
        usd, = self.currency_obj.create([{
            'name': 'US Dollar',
            'code': 'USD',
            'symbol': '$',
        }])
        self.party, = self.party_obj.create([{
            'name': 'Openlabs',
        }])
        self.company, = self.company_obj.create([{
            'party': self.party,
            'currency': usd,
        }])
        self.guest_party, = self.party_obj.create([{
            'name': 'Guest User',
        }])
        self.guest_user, = self.nereid_user_obj.create([{
            'party': self.guest_party,
            'display_name': 'Guest User',
            'email': 'guest@openlabs.co.in',
            'password': 'password',
            'company': self.company.id,
        }])
        self.create_countries()
        self.available_countries = self.country_obj.search([], limit=5)

        url_map_id, = self.url_map_obj.search([], limit=1)
        en_us, = self.language_obj.search([('code', '=', 'en_US')])
        currency, = self.currency_obj.search([('code', '=', 'USD')])
        locale, = self.nereid_website_locale_obj.create([{
            'code': 'en-us',
            'language': en_us,
            'currency': currency,
        }])
        self.nereid_website_obj.create([{
            'name': 'localhost',
            'url_map': url_map_id,
            'company': self.company,
            'application_user': USER,
            'default_locale': locale,
            'locales': [('add', [locale.id])],
            'guest_user': self.guest_user,
            'countries': [('set', self.available_countries)],
        }])

    def get_app(self, **options):
        app = NereidTestApp(
            template_folder=os.path.abspath(
                os.path.join(os.path.dirname(__file__), 'templates')
            )
        )
        app.config['TEMPLATE_PREFIX_WEBSITE_NAME'] = False
        app.config.update(options)
        app.config['DATABASE_NAME'] = DB_NAME
        app.config['DEBUG'] = True
        app.session_interface.session_store = \
            FilesystemSessionStore('/tmp', session_class=Session)

        # Initialise the app now
        app.initialise()

        # Load babel as its a required extension anyway
        Babel(app)
        return app


class TestTemplateLoading(BaseTestCase):
    '''
    Test the loading of templates
    '''

    def test_0005_loaders(self):
        '''
        Confirm the paths in the loaders
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            # There must be two loaders, one from the searchpath
            # relative to this folder and the other from
            # nereid package
            self.assertEqual(len(app.jinja_loader.loaders), 2)

    def test_0010_local_loading(self):
        '''
        Render template from local searchpath
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_request_context('/'):
                self.assertEqual(
                    render_template('from-local.html'),
                    'from-local-folder'
                )

    def test_0020_module_loading(self):
        '''
        Render template from module templates searchpath
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_request_context('/'):
                self.assertEqual(
                    render_template('tests/from-module.html'),
                    'from-module'
                )

    def test_0030_local_overwrites_module(self):
        '''
        Look for a template which has a local presence and also
        in the package, but the one rendered is from the local folder
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_request_context('/'):
                self.assertEqual(
                    render_template('tests/exists-both.html'),
                    'content-from-local'
                )

    def test_0040_inheritance(self):
        '''Test if templates are read in the order of the tryton
        module dependency graph. To test this we install the test
        module now and then try to load a template which is different
        with the test module.
        '''
        trytond.tests.test_tryton.install_module('nereid_test')

        with Transaction().start(DB_NAME, USER, CONTEXT) as txn:  # noqa
            # Add nereid_test also to list of modules installed so
            # that it is also added to the templates path

            self.setup_defaults()
            app = self.get_app()

            self.assertEqual(len(app.jinja_loader.loaders), 3)

            with app.test_request_context('/'):
                self.assertEqual(
                    render_template('tests/from-module.html'),
                    'from-nereid-test-module'
                )

    def test_0050_prefix_loader(self):
        """
        Test the SiteNamePrefixLoader
        """
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app(
                TEMPLATE_PREFIX_WEBSITE_NAME=True
            )

            with app.test_request_context('/'):
                self.assertEqual(
                    render_template('site-specific-template.html'),
                    'content-from-localhost-site-specific-template'
                )


class TestLazyRendering(BaseTestCase):
    '''
    Test the lazy rendering of templates
    '''

    def test_0010_change_context(self):
        '''
        Render template from local searchpath
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_request_context('/'):
                self.assertEqual(
                    render_template(
                        'tests/test-changing-context.html',
                        variable="a"
                    ), 'a'
                )
                lazy_template = render_template(
                    'tests/test-changing-context.html',
                    variable="a"
                )
                self.assertTrue(
                    isinstance(lazy_template, LazyRenderer)
                )

                # Now change the value of the variable in the context and
                # see if the template renders with the new value
                lazy_template.context['variable'] = "b"
                self.assertEqual(lazy_template, "b")

                # Make a unicode of the same template
                unicode_of_response = unicode(lazy_template)
                self.assertEqual(unicode_of_response, "b")
                self.assertTrue(
                    isinstance(unicode_of_response, unicode)
                )

    def test_0020_pickling(self):
        '''
        Test if the lazy rendering object can be pickled and rendered
        with a totally different context (when no application, request
        or transaction bound objects are present).
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_request_context('/'):
                response = render_template(
                    'tests/test-changing-context.html',
                    variable="a"
                )
                self.assertEqual(response, 'a')
                pickled_response = pickle.dumps(response)

        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_request_context('/'):
                response = pickle.loads(pickled_response)
                self.assertEqual(response, 'a')

    def test_0030_simple_render(self):
        '''
        Simply render a template.
        '''
        with Transaction().start(DB_NAME, USER, CONTEXT):
            self.setup_defaults()
            app = self.get_app()

            with app.test_client() as c:
                response = c.get('/en_US/registration')
                self.assertEqual(response.status_code, 200)


def suite():
    "Nereid Template Loading test suite"
    test_suite = unittest.TestSuite()
    test_suite.addTests([
        unittest.TestLoader().loadTestsFromTestCase(TestTemplateLoading),
        unittest.TestLoader().loadTestsFromTestCase(TestLazyRendering),
    ])
    return test_suite


if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
