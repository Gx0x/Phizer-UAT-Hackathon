"""Offline handover checks with fake database RPCs and AI. No network required."""
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4
from fastapi import HTTPException
from app.models import DeveloperStatusUpdate, TechnicalContent, TechnicalDraftUpdate
from app.services import handoff as service, consolidated, logs
from scripts.test_detail_requests import DetailDB, DetailTable, TESTER, OTHER, NOW, BASE
CONTENT = dict(title='Export stalls', problem_summary='The export keeps spinning without downloading.', expected_behaviour='A file should download.', actual_behaviour='A spinner persists.', reproduction_steps='Report 1: Click Export.', environment='Export page, Chrome.', log_notes='A timeout event is a possible investigation lead.', priority='medium', included_log_ids=[])
EVENT = dict(timestamp=NOW, service='ExportService', level='ERROR', message='Export download timeout', error_code='EXPORT_TIMEOUT')
SOURCE_KEYS = ('issue_id', 'answers', 'follow_up_question', 'follow_up_answer', 'occurred_at', 'detail_revision')

class HandoffTable(DetailTable):

    def eq(self, column, value):
        if '.' in column:
            self.path_filters = getattr(self, 'path_filters', []) + [(column, value)]
            return self
        return super().eq(column, value)

    def execute(self):
        before = copy.deepcopy(self.db.tables['reports'])
        result = super().execute()
        if self.name == 'reports' and self.op != 'select':
            previous = {row['id']: row for row in before}
            current = {row['id']: row for row in self.db.tables['reports']}
            for id in previous.keys() | current.keys():
                old, new = (previous.get(id, {}), current.get(id, {}))
                if any((old.get(key) != new.get(key) for key in SOURCE_KEYS)):
                    for parent in {old.get('issue_id'), new.get('issue_id')} - {None}:
                        if self.db.issue(parent).get('handoff_status') == 'forwarded':
                            self.db.reopen(parent)
        if self.op == 'select' and self.name == 'issues':
            for row in result.data:
                row['reports'] = [{**copy.deepcopy(report), 'detail_requests': self.db.history(report['id'])} for report in self.db.tables['reports'] if report['issue_id'] == row['id']]
        if self.op == 'select' and self.name == 'developer_tickets':
            for row in result.data:
                row['issues'] = {'handoff_status': self.db.issue(row['issue_id']).get('handoff_status', 'review')}
            for key, value in getattr(self, 'path_filters', []):
                result.data = [row for row in result.data if row.get(key.split('.')[0], {}).get(key.split('.')[1]) == value]
        if self.op == 'select' and self.name == 'reports':
            for row in result.data:
                parent = self.db.issue(row['issue_id'])
                ticket = next((item for item in self.db.tables['developer_tickets'] if item['issue_id'] == row['issue_id']), None)
                row['issues'] = {'handoff_status': parent.get('handoff_status', 'review'), 'developer_tickets': copy.deepcopy(ticket)}
        return result

class HandoffDB(DetailDB):

    def __init__(self):
        super().__init__()
        self.tables.update(technical_drafts=[], developer_tickets=[])

    def table(self, name):
        return HandoffTable(self, name)

    def sources(self, id):
        return consolidated.source_snapshot([{**row, 'detail_requests': self.history(row['id'])} for row in self.tables['reports'] if row['issue_id'] == id])

    def draft(self, id):
        return next((row for row in self.tables['technical_drafts'] if row['issue_id'] == id), None)

    def ticket(self, id):
        return next((row for row in self.tables['developer_tickets'] if row['issue_id'] == id), None)

    def reopen(self, id):
        self.issue(id).update(handoff_status='review', forwarded_at=None)
        ticket = self.ticket(id)
        if ticket and ticket['active']:
            ticket.update(active=False, revision=ticket['revision'] + 1)
        draft = self.draft(id)
        if draft:
            draft['revision'] += 1

    def save_draft(self, p):
        id = p['p_issue_id']
        if self.issue(id).get('handoff_status') == 'forwarded':
            return {'status': 'forwarded'}
        draft = self.draft(id)
        if not draft:
            return {'status': 'no_draft'}
        if draft['revision'] != p['p_expected_revision']:
            return {'status': 'revision_changed'}
        if self.sources(id) != draft['source_snapshot']['reports']:
            return {'status': 'sources_changed'}
        draft.update(content=copy.deepcopy(p['p_content']), revision=draft['revision'] + 1)
        return {'status': 'saved', 'draft': copy.deepcopy(draft)}

    def rpc(self, name, p):
        if name not in {'store_technical_draft', 'save_technical_draft', 'approve_technical_handoff', 'reopen_technical_handoff', 'update_developer_ticket_status'}:
            return super().rpc(name, p)
        db = self

        class Operation:

            def execute(self):
                db.maybe_fail('rpc', name)
                id = p.get('p_issue_id')
                if name == 'store_technical_draft':
                    if db.issue(id).get('handoff_status') == 'forwarded':
                        result = {'status': 'forwarded'}
                    elif db.sources(id) != p['p_context']['reports']:
                        result = {'status': 'sources_changed'}
                    else:
                        draft = db.draft(id)
                        revision = draft['revision'] + 1 if draft else 1
                        if draft:
                            db.tables['technical_drafts'].remove(draft)
                        draft = dict(id=str(uuid4()), issue_id=id, content=copy.deepcopy(p['p_content']), source_snapshot=copy.deepcopy(p['p_context']), generation_status=p['p_generation_status'], revision=revision, created_at=NOW, updated_at=NOW)
                        db.tables['technical_drafts'].append(draft)
                        result = {'status': 'saved', 'draft': copy.deepcopy(draft)}
                elif name == 'save_technical_draft':
                    result = db.save_draft(p)
                elif name == 'approve_technical_handoff':
                    active = [item for item in db.tables['detail_requests'] if item['status'] in ('draft', 'pending') and db.report(item['report_id'])['issue_id'] == id]
                    if active:
                        result = {'status': 'open_requests'}
                    else:
                        result = db.save_draft(p)
                        if result['status'] == 'saved':
                            draft = db.draft(id)
                            ticket = db.ticket(id)
                            content = copy.deepcopy(p['p_content'])
                            content['supporting_logs'] = [row for row in draft['source_snapshot']['log_candidates'] if row['id'] in content['included_log_ids']]
                            if ticket:
                                ticket.update(content=content, source_snapshot={'reports': copy.deepcopy(draft['source_snapshot']['reports'])}, active=True, status='todo', revision=ticket['revision'] + 1)
                            else:
                                ticket = dict(id=str(uuid4()), issue_id=id, content=content, source_snapshot={'reports': copy.deepcopy(draft['source_snapshot']['reports'])}, active=True, status='todo', revision=1, approved_at=NOW, updated_at=NOW)
                                db.tables['developer_tickets'].append(ticket)
                            db.issue(id).update(handoff_status='forwarded', forwarded_at=NOW)
                            result = {'status': 'forwarded', 'ticket_id': ticket['id']}
                elif name == 'reopen_technical_handoff':
                    db.reopen(id)
                    result = {'status': 'reopened'}
                else:
                    ticket = next((row for row in db.tables['developer_tickets'] if row['id'] == p['p_ticket_id']), None)
                    if not ticket:
                        result = {'status': 'not_found'}
                    elif not ticket['active'] or db.issue(ticket['issue_id']).get('handoff_status') != 'forwarded':
                        result = {'status': 'withdrawn'}
                    elif ticket['revision'] != p['p_expected_revision']:
                        result = {'status': 'revision_changed'}
                    else:
                        ticket.update(status=p['p_status'], revision=ticket['revision'] + 1)
                        result = {'status': 'saved', 'ticket': copy.deepcopy(ticket)}
                return types.SimpleNamespace(data=result)
        return Operation()

class HandoffTests(unittest.TestCase):

    def setUp(self):
        try:
            import app.db
        except ModuleNotFoundError:
            module = types.ModuleType('app.db')
            module.get_supabase = lambda: None
            sys.modules['app.db'] = module
        from app.routers import handoff, detail_requests
        self.router = handoff
        self.requests = detail_requests
        self.db = HandoffDB()
        self.issue, self.report = self.db.seed_issue('Export hangs', 'bug', BASE, answers={'actual': 'Export download hangs', 'steps': 'Click Export', 'page': 'Export page', 'browser': 'Chrome'})
        self.issue['handoff_status'] = 'review'
        self.report.update(tester_id=TESTER, created_at=NOW, occurred_at=NOW, detail_revision=0, follow_up_question=None, follow_up_answer=None)
        for item in [patch.object(handoff, 'get_supabase', return_value=self.db), patch.object(detail_requests, 'get_supabase', return_value=self.db), patch.object(logs, 'load_log_entries', return_value=[EVENT]), patch.object(service, 'call_llm', return_value=json.dumps(CONTENT))]:
            item.start()
            self.addCleanup(item.stop)

    def generate(self):
        return self.router.generate_technical_draft(UUID(self.issue['id']))['draft']

    def payload(self, content=None, revision=None):
        draft = self.db.draft(self.issue['id'])
        return TechnicalDraftUpdate(expected_revision=revision or draft['revision'], content=content or draft['content'])

    def approve(self, content=None):
        return self.router.approve_handoff(UUID(self.issue['id']), self.payload(content))

    def test_generation_creates_only_a_draft(self):
        draft = self.generate()
        self.assertEqual(draft['generation_status'], 'ok')
        self.assertEqual(self.db.tables['developer_tickets'], [])
        self.assertEqual(self.router.list_developer_tickets(), [])
        self.assertEqual(self.issue['handoff_status'], 'review')

    def test_excluded_sections_are_absent(self):
        content = self.generate()['content']
        self.assertNotIn('missing_information', content)
        self.assertNotIn('acceptance_criteria', content)
        self.assertEqual(set(content), set(TechnicalContent.model_fields))

    def test_ai_failure_gives_editable_fallback(self):
        with patch.object(service, 'call_llm', side_effect=TimeoutError()):
            draft = self.generate()
        self.assertEqual(draft['generation_status'], 'fallback')
        self.assertIn('Export download hangs', draft['content']['problem_summary'])
        self.assertEqual(self.db.tables['developer_tickets'], [])

    def test_bad_model_shape_falls_back(self):
        for raw in ['{}', 'banana', json.dumps({**CONTENT, 'missing_information': []})]:
            with patch.object(service, 'call_llm', return_value=raw):
                draft = self.generate()
            self.assertEqual(draft['generation_status'], 'fallback')

    def test_draft_uses_replies_and_log_context(self):
        self.db.tables['detail_requests'].append(dict(id=str(uuid4()), report_id=self.report['id'], question='Which page?', answer='Page 1', status='answered', answered_at=NOW))
        seen = []

        def llm(system, user, **kwargs):
            seen.append(json.loads(user))
            return json.dumps(CONTENT)
        with patch.object(service, 'call_llm', side_effect=llm):
            self.generate()
        self.assertEqual(seen[0]['reports'][0]['manager_clarifications'][0]['answer'], 'Page 1')
        self.assertTrue(seen[0]['log_candidates'])

    def test_manager_edits_are_saved_without_forwarding(self):
        self.generate()
        content = {**CONTENT, 'title': 'Manager edited title', 'priority': 'high'}
        self.router.save_technical_draft(UUID(self.issue['id']), self.payload(content))
        self.assertEqual(self.db.draft(self.issue['id'])['content']['title'], 'Manager edited title')
        self.assertEqual(self.db.tables['developer_tickets'], [])

    def test_approval_publishes_exact_reviewed_fields(self):
        self.generate()
        content = {**CONTENT, 'title': 'Reviewed export bug', 'priority': 'critical'}
        self.approve(content)
        ticket = self.db.ticket(self.issue['id'])
        self.assertEqual(ticket['content']['title'], 'Reviewed export bug')
        self.assertEqual(ticket['content']['priority'], 'critical')
        self.assertEqual(ticket['status'], 'todo')
        self.assertEqual(self.issue['handoff_status'], 'forwarded')
        self.assertEqual(len(self.router.list_developer_tickets()), 1)

    def test_unselected_logs_are_not_forwarded(self):
        self.generate()
        self.approve()
        self.assertEqual(self.db.ticket(self.issue['id'])['content']['supporting_logs'], [])

    def test_selected_logs_keep_original_messages(self):
        self.generate()
        id = self.db.draft(self.issue['id'])['source_snapshot']['log_candidates'][0]['id']
        self.approve({**CONTENT, 'included_log_ids': [id]})
        self.assertEqual(self.db.ticket(self.issue['id'])['content']['supporting_logs'][0]['message'], EVENT['message'])

    def test_fabricated_log_id_is_rejected(self):
        self.generate()
        with self.assertRaises(HTTPException) as caught:
            self.approve({**CONTENT, 'included_log_ids': ['invented']})
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.db.tables['developer_tickets'], [])

    def test_stale_revision_is_rejected(self):
        draft = self.generate()
        old = self.payload(revision=draft['revision'])
        self.router.save_technical_draft(UUID(self.issue['id']), self.payload())
        with self.assertRaises(HTTPException) as caught:
            self.router.approve_handoff(UUID(self.issue['id']), old)
        self.assertEqual(caught.exception.status_code, 409)

    def test_new_sources_require_regeneration(self):
        self.generate()
        self.report['detail_revision'] += 1
        with self.assertRaises(HTTPException) as caught:
            self.approve()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertFalse(self.router.get_technical_draft(UUID(self.issue['id']))['source_is_current'])

    def test_open_questions_block_approval(self):
        self.generate()
        self.db.tables['detail_requests'].append(dict(id=str(uuid4()), report_id=self.report['id'], status='draft'))
        with self.assertRaises(HTTPException) as caught:
            self.approve()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.tables['developer_tickets'], [])

    def test_approval_storage_failure_does_not_forward(self):
        self.generate()
        self.db.fail('rpc', 'approve_technical_handoff')
        with self.assertRaises(HTTPException) as caught:
            self.approve()
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(self.issue['handoff_status'], 'review')
        self.assertEqual(self.db.tables['developer_tickets'], [])

    def test_duplicate_approval_creates_one_ticket(self):
        self.generate()
        self.approve()
        with self.assertRaises(HTTPException) as caught:
            self.approve()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(self.db.tables['developer_tickets']), 1)

    def test_developer_can_update_both_requested_statuses(self):
        self.generate()
        self.approve()
        ticket = self.db.ticket(self.issue['id'])
        for status in ['in_progress', 'ready_for_retest']:
            self.router.update_ticket_status(UUID(ticket['id']), DeveloperStatusUpdate(expected_revision=ticket['revision'], status=status))
            self.assertEqual(ticket['status'], status)

    def test_stale_developer_update_is_rejected(self):
        self.generate()
        self.approve()
        ticket = self.db.ticket(self.issue['id'])
        old = DeveloperStatusUpdate(expected_revision=ticket['revision'], status='in_progress')
        self.router.update_ticket_status(UUID(ticket['id']), old)
        with self.assertRaises(HTTPException) as caught:
            self.router.update_ticket_status(UUID(ticket['id']), old)
        self.assertEqual(caught.exception.status_code, 409)

    def test_reopen_withdraws_active_ticket(self):
        self.generate()
        self.approve()
        self.router.reopen_handoff(UUID(self.issue['id']))
        self.assertEqual(self.issue['handoff_status'], 'review')
        self.assertEqual(self.router.list_developer_tickets(), [])
        self.assertTrue(self.db.ticket(self.issue['id'])['content'])

    def test_withdrawn_ticket_cannot_be_updated(self):
        self.generate()
        self.approve()
        ticket = self.db.ticket(self.issue['id'])
        self.router.reopen_handoff(UUID(self.issue['id']))
        with self.assertRaises(HTTPException) as caught:
            self.router.update_ticket_status(UUID(ticket['id']), DeveloperStatusUpdate(expected_revision=ticket['revision'], status='in_progress'))
        self.assertEqual(caught.exception.status_code, 409)

    def test_reapproval_reuses_ticket_and_restarts_todo(self):
        self.generate()
        self.approve()
        ticket = self.db.ticket(self.issue['id'])
        id = ticket['id']
        ticket['status'] = 'in_progress'
        self.router.reopen_handoff(UUID(self.issue['id']))
        self.approve({**CONTENT, 'title': 'Reviewed again'})
        self.assertEqual(ticket['id'], id)
        self.assertEqual(ticket['status'], 'todo')
        self.assertEqual(ticket['content']['title'], 'Reviewed again')

    def test_source_change_withdraws_an_approved_snapshot(self):
        self.generate()
        self.approve()
        self.db.table('reports').update({'follow_up_answer': 'New page information'}).eq('id', self.report['id']).execute()
        self.assertEqual(self.issue['handoff_status'], 'review')
        self.assertEqual(self.router.list_developer_tickets(), [])

    def test_quality_metadata_alone_does_not_withdraw(self):
        self.generate()
        self.approve()
        self.db.table('reports').update({'ai_quality': {'status': 'unavailable'}}).eq('id', self.report['id']).execute()
        self.assertEqual(self.issue['handoff_status'], 'forwarded')

    def test_forwarded_issue_requires_reopening_before_questions(self):
        self.generate()
        self.approve()
        with self.assertRaises(HTTPException) as caught:
            self.requests.mark_needs_detail(UUID(self.report['id']))
        self.assertEqual(caught.exception.status_code, 409)

    def test_tester_progress_tracks_developer_status(self):
        self.generate()
        self.approve()
        ticket = self.db.ticket(self.issue['id'])
        self.assertEqual(self.router.tester_report_status(UUID(TESTER))[0]['status'], 'forwarded')
        ticket['status'] = 'ready_for_retest'
        self.assertEqual(self.router.tester_report_status(UUID(TESTER))[0]['status'], 'ready_for_retest')
        self.assertEqual(self.router.tester_report_status(UUID(OTHER)), [])

    def test_counts_and_original_reports_are_unchanged(self):
        original = copy.deepcopy(self.report['answers'])
        self.generate()
        self.approve()
        self.router.reopen_handoff(UUID(self.issue['id']))
        self.assertEqual(self.issue['report_count'], 1)
        self.assertEqual(self.report['answers'], original)

    def test_blank_title_and_invalid_status_are_rejected(self):
        with self.assertRaises(ValueError):
            TechnicalContent(**{**CONTENT, 'title': '  '})
        with self.assertRaises(ValueError):
            DeveloperStatusUpdate(expected_revision=1, status='closed')

def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HandoffTests)
    count = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f'PASS: all {count} offline cases')
    return 0 if result.wasSuccessful() else 1
if __name__ == '__main__':
    sys.exit(main())
