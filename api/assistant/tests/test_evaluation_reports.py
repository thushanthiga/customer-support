from django.test import SimpleTestCase
from assistant.evaluation_reports import report_for_storage


class EvaluationReportTests(SimpleTestCase):
    def test_summary_omits_business_evidence_without_changing_in_memory_report(self):
        report={'cases':[{'id':'example','turns':[{'question':'Check payroll','answer':'private-payroll-canary',
            'tools':[{'result':'private-payroll-canary'}],'oracle':'private-payroll-canary',
            'scalar_snapshot':'private-payroll-canary','failures':[],
            'provider_calls':[{'completed':True,'proposal':{'plans':[]}}]}]}]}
        summary=report_for_storage(report)
        self.assertNotIn('private-payroll-canary',str(summary))
        self.assertNotIn('proposal',summary['cases'][0]['turns'][0]['provider_calls'][0])
        self.assertEqual(report['cases'][0]['turns'][0]['answer'],'private-payroll-canary')

    def test_evidence_requires_explicit_detail_and_is_labelled(self):
        saved=report_for_storage({'cases':[{'turns':[{'answer':'local evidence'}]}]},'evidence')
        self.assertEqual(saved['cases'][0]['turns'][0]['answer'],'local evidence')
        self.assertEqual(saved['report_detail'],'evidence')

    def test_unknown_future_evidence_fields_are_not_silently_stored_in_summary(self):
        report={'cases':[{'turns':[{'response':'private-canary','data_pages':'private-canary',
            'row_snapshots':'private-canary','new_evidence':'private-canary','answer_status':'answered'}]}],
            'fixture_checks':[{'check':'fixture','passed':True,'evidence':'private-canary'}],
            'targeted_local_rechecks':[{'id':'example','passed':True,'query_audit':'private-canary'}]}
        summary=report_for_storage(report)
        self.assertNotIn('private-canary',str(summary))
        self.assertTrue(summary['fixture_checks'][0]['passed'])
