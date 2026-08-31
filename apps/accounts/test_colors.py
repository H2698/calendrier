import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .colors import CALENDAR_PALETTE, available_calendar_color
from .forms import TeamMemberForm
from .models import Profile
from .services import create_user_account


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CalendarColorTests(TestCase):
    password = 'test-calendar-colors-strong-password'

    @classmethod
    def setUpTestData(cls):
        cls.admin = create_user_account(
            email='color-admin@example.test', password=cls.password,
            full_name='Color Admin', role=Profile.Role.ADMIN,
        )

    def login(self):
        self.client.force_login(self.admin, backend='apps.accounts.backends.EmailBackend')

    def data(self, **overrides):
        return {
            'email': 'new-color@example.test', 'password': self.password,
            'full_name': 'New Color', 'role': 'member', **overrides,
        }

    def test_service_assigns_unused_colors_and_preserves_existing_profiles(self):
        before = dict(Profile.objects.values_list('pk', 'calendar_color'))
        created = [create_user_account(**self.data(email=f'color-{index}@example.test')) for index in range(4)]
        colors = [user.profile.calendar_color for user in created]
        self.assertEqual(len(set(colors)), 4)
        self.assertNotIn(self.admin.profile.calendar_color, colors)
        self.assertEqual(dict(Profile.objects.filter(pk__in=before).values_list('pk', 'calendar_color')), before)

    def test_create_page_shows_unused_preview_and_native_picker(self):
        self.login()
        page = self.client.get(reverse('accounts:team'))
        form = page.context['form']
        self.assertNotEqual(form['calendar_color'].value(), self.admin.profile.calendar_color)
        self.assertTrue(form['automatic_color'].value())
        self.assertContains(page, 'type="color"')
        self.assertContains(page, 'data-calendar-color')
        self.assertContains(page, 'js/calendar-color.js')
        self.assertContains(page, form['calendar_color'].value())

    def test_automatic_post_recomputes_a_stale_preview(self):
        self.login()
        suggested = TeamMemberForm()['calendar_color'].value()
        other = create_user_account(**self.data(email='other-color@example.test'))
        self.assertEqual(other.profile.calendar_color, suggested)
        result = self.client.post(reverse('accounts:team'), self.data(
            automatic_color='on', calendar_color=suggested,
        ))
        self.assertRedirects(result, reverse('accounts:team'))
        new = get_user_model().objects.get(email='new-color@example.test')
        self.assertNotIn(new.profile.calendar_color, (suggested, self.admin.profile.calendar_color))

    def test_automatic_form_accepts_no_color_and_manual_choice_is_preserved(self):
        self.login()
        response = self.client.post(reverse('accounts:team'), self.data(automatic_color='on'))
        self.assertRedirects(response, reverse('accounts:team'))
        response = self.client.post(reverse('accounts:team'), self.data(
            email='custom-color@example.test', calendar_color='#ab23cd',
        ))
        self.assertRedirects(response, reverse('accounts:team'))
        user = get_user_model().objects.get(email='custom-color@example.test')
        self.assertEqual(user.profile.calendar_color, '#ab23cd')

    def test_api_assigns_automatic_color_when_omitted_and_keeps_custom_color(self):
        self.login()
        for index, color in enumerate((None, '', '#AB23CD')):
            payload = self.data(email=f'api-color-{index}@example.test')
            if color is not None:
                payload['calendar_color'] = color
            response = self.client.post(
                reverse('accounts:team-create-api'), json.dumps(payload), content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)
            actual = response.json()['data']['calendar_color']
            if color:
                self.assertEqual(actual, color)
            else:
                self.assertNotEqual(actual, self.admin.profile.calendar_color)
        self.assertEqual(Profile.objects.values('calendar_color').distinct().count(), 4)

    def test_palette_does_not_reuse_lowercase_or_inactive_members_colors(self):
        self.admin.profile.calendar_color = CALENDAR_PALETTE[0].lower()
        self.admin.profile.is_active = False
        self.admin.profile.save()
        self.assertNotEqual(available_calendar_color().upper(), CALENDAR_PALETTE[0])

    def test_palette_extends_after_all_predefined_colors_are_used(self):
        for index, color in enumerate(CALENDAR_PALETTE[1:]):
            create_user_account(**self.data(email=f'palette-{index}@example.test', calendar_color=color))
        new = create_user_account(**self.data())
        self.assertNotIn(new.profile.calendar_color, CALENDAR_PALETTE)
        self.assertRegex(new.profile.calendar_color, r'^#[0-9A-F]{6}$')
        self.assertNotEqual(available_calendar_color(), new.profile.calendar_color)

    def test_invalid_manual_color_stays_a_form_error(self):
        self.login()
        for value in ('', 'invalid', '#FFF'):
            with self.subTest(value=value):
                response = self.client.post(reverse('accounts:team'), self.data(calendar_color=value))
                self.assertEqual(response.status_code, 200)
                self.assertIn('calendar_color', response.context['form'].errors)
                self.assertFalse(get_user_model().objects.filter(email='new-color@example.test').exists())

    def test_validation_error_keeps_custom_choice_and_automatic_checkbox(self):
        self.login()
        for automatic in ('', 'on'):
            response = self.client.post(reverse('accounts:team'), self.data(
                email=self.admin.email, calendar_color='#123abc', automatic_color=automatic,
            ))
            self.assertEqual(response.status_code, 200)
            form = response.context['form']
            self.assertIn('email', form.errors)
            self.assertEqual(form['calendar_color'].value(), '#123abc')
            self.assertEqual(form['automatic_color'].value(), bool(automatic))

    def test_edit_and_settings_show_picker_without_changing_existing_color(self):
        self.login()
        original = self.admin.profile.calendar_color
        for name, kwargs in (
            ('accounts:team-member', {'user_id': self.admin.pk}), ('accounts:settings', {}),
        ):
            page = self.client.get(reverse(name, kwargs=kwargs))
            self.assertContains(page, 'type="color"')
            self.assertContains(page, 'js/calendar-color.js')
            self.assertContains(page, original)
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.profile.calendar_color, original)
