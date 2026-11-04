from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from assistant.local_engine import answer
from assistant.query_service import execute

@override_settings(DEMO_MODE=True)
class AssistantTests(TestCase):
    def test_documentation_route(self):
        result = answer('Where can we create sales?', [], 'demo')
        self.assertEqual(result['kind'], 'guidance')
        self.assertIn('Sales → POS → POS Sales → New Sale', result['text'])
    def test_comparison(self):
        result = answer('List POS sales under 50', [], 'demo')
        self.assertEqual(len(result['rows']), 3)
        self.assertTrue(all(r['total'] < 50 for r in result['rows']))
    def test_ambiguous(self):
        self.assertEqual(answer('I need sales', [], 'demo')['kind'], 'clarification')
    def test_unsupported_filters_are_not_ignored(self):
        self.assertEqual(answer('List sales yesterday', [], 'demo')['kind'], 'clarification')
        self.assertEqual(answer('List sales under 50 over 100', [], 'demo')['kind'], 'clarification')
    def test_follow_up(self):
        self.assertEqual(len(answer('over 100', ['List POS sales'], 'demo')['rows']), 1)
    def test_arbitrary_plan_rejected(self):
        with self.assertRaises(ValueError):
            execute({'entity':'users','operator':None,'amount':None,'limit':50}, 'demo')
    def test_auth_and_conversation_isolation(self):
        owner = User.objects.create_user(username='owner', password='test-pass')
        other = User.objects.create_user(username='other', password='test-pass')
        self.assertEqual(self.client.get('/api/sessions/').status_code, 403)
        self.client.force_login(owner)
        result = self.client.post('/api/chat/', {'message':'List POS sales'}, content_type='application/json')
        self.assertEqual(result.status_code, 200)
        session_id = result.json()['session_id']
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/api/sessions/{session_id}/').status_code, 404)
    @override_settings(DEMO_MODE=False, ERP_TENANT_ID='tenant-a')
    def test_live_access_requires_tenant_grant(self):
        user = User.objects.create_user(username='restricted', password='test-pass')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/api/sessions/').status_code, 403)
    def test_csrf_enforced(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/login/', {}, content_type='application/json').status_code, 403)

    def test_browser_login_and_chat_with_csrf(self):
        from django.test import Client
        User.objects.create_user(username="browser", password="test-pass")
        client = Client(enforce_csrf_checks=True)
        client.get("/api/bootstrap/")
        response = client.post("/api/login/", {"username":"browser", "password":"test-pass"}, content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200)
        response = client.post("/api/chat/", {"message":"List POS sales under 50"}, content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["rows"]), 3)
