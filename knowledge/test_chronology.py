import json
from django.test import SimpleTestCase
from .chronology import resolve_latest_employer, ChronologyError, date_bounds, is_latest_employer_question


class EmploymentDateTests(SimpleTestCase):
    def resolve(self, text, records, question='latest employer'):
        sources=[{'id':'1','document_id':1,'chunk_id':1,'position':0,'excerpt':text}]
        return json.loads(resolve_latest_employer(json.dumps({'employment_history':records}),sources,question))

    def record(self,name,start,end):
        return {'employer':name,'start_date':start,'end_date':end,'source_ids':['1']}

    def test_year_and_month_formats_sort_as_calendar_dates(self):
        self.assertEqual(date_bounds('03/2025'),date_bounds('March 2025'))
        self.assertEqual(date_bounds('2025-03'),date_bounds('Mar 2025'))
        self.assertGreater(date_bounds('01/2025'),date_bounds('12/2024'))

    def test_reverse_document_order_does_not_determine_latest(self):
        records=[self.record('Recent Co','November 2022','March 2025'),self.record('Older Co','August 2019','December 2021')]
        result=self.resolve('WORK EXPERIENCE Recent Co November 2022 – March 2025. Older Co August 2019 – December 2021.',records)
        self.assertIn('Recent Co',result['answer'])

    def test_present_role_sorts_after_completed_roles(self):
        result=self.resolve('WORK EXPERIENCE Completed Co 2023 - 2025. Active Co 2024 - Present.',[
            self.record('Completed Co','2023','2025'),self.record('Active Co','2024','Present')])
        self.assertIn('Active Co',result['answer'])

    def test_latest_ended_role_is_not_claimed_to_be_current(self):
        result=self.resolve('WORK EXPERIENCE Ended Co 2022 - 2025.',[self.record('Ended Co','2022','2025')],'current employer')
        self.assertIn('No ongoing employer is explicitly stated',result['answer'])

    def test_future_education_is_excluded_from_date_coverage(self):
        result=self.resolve('WORK EXPERIENCE Employer Co 2022 - 2025. EDUCATION University 2024 - 2028.',[self.record('Employer Co','2022','2025')])
        self.assertIn('Employer Co',result['answer'])

    def test_invented_dates_are_rejected_even_with_valid_source_id(self):
        with self.assertRaises(ChronologyError):
            self.resolve('WORK EXPERIENCE Employer Co 2022 - 2025.',[self.record('Employer Co','2022','Present')])

    def test_dates_cannot_be_attached_to_the_wrong_employer(self):
        with self.assertRaises(ChronologyError):
            self.resolve('WORK EXPERIENCE First Co 2019 - 2021. Second Co 2022 - 2025.',[
                self.record('First Co','2022','2025'),self.record('Second Co','2019','2021')])

    def test_indistinguishable_or_imprecise_dates_are_not_guessed(self):
        with self.assertRaises(ChronologyError):
            self.resolve('WORK EXPERIENCE One Co 2020 - 2025. Two Co 2020 - 03/2025.',[
                self.record('One Co','2020','2025'),self.record('Two Co','2020','03/2025')])

    def test_normal_questions_do_not_trigger_employment_mode(self):
        self.assertFalse(is_latest_employer_question('What is the candidate name?'))
        self.assertFalse(is_latest_employer_question('What is the latest Python version?'))
        self.assertTrue(is_latest_employer_question('Which company did she last work for?'))


    def test_company_word_is_not_mistaken_for_month_name(self):
        with self.assertRaises(ChronologyError):
            self.resolve('WORK EXPERIENCE Older Co 2019 - 2021. Example Labs 2022 - 2025.',[
                self.record('Older Co','2019','2021')])

    def test_valid_latest_job_does_not_require_repeating_older_jobs(self):
        result=self.resolve('WORK EXPERIENCE Older Co 2019 - 2021. Example Labs 2022 - 2025.',[
            self.record('Example Labs','2022','2025')])
        self.assertIn('Example Labs',result['answer'])


    def test_recently_and_employed_wording_trigger_date_comparison(self):
        self.assertTrue(is_latest_employer_question('Which company did she work for most recently?'))
        self.assertTrue(is_latest_employer_question('Where was she most recently employed?'))


    def test_common_spelling_variants_and_job_wording_use_same_date_checks(self):
        for question in [
            'what is the recent employement', 'most recent emplyoment',
            'what is recent employemnt', 'what is the recnet employement',
            'what is her latest role', 'recent job', 'latest position',
        ]:
            with self.subTest(question=question):
                self.assertTrue(is_latest_employer_question(question))
        for question in ['recent deployment', 'latest development project', 'what is her name?']:
            with self.subTest(question=question):
                self.assertFalse(is_latest_employer_question(question))

    def test_employment_wording_includes_source_supported_role(self):
        record={**self.record('Healthcare Co','11/2022','03/2025'),'role':'Work Student'}
        result=self.resolve('WORK EXPERIENCE Work Student Healthcare Co 11/2022 - 03/2025.',[record],'what is the recent employement')
        self.assertIn('Work Student at Healthcare Co',result['answer'])
        self.assertIn('03/2025',result['answer'])

    def test_professional_summary_title_is_not_used_as_latest_job_title(self):
        record={**self.record('Healthcare Co','11/2022','03/2025'),'role':'Data Scientist'}
        result=self.resolve('Data Scientist. WORK EXPERIENCE Work Student Healthcare Co 11/2022 - 03/2025.',[record],'recent employment')
        self.assertIn('Healthcare Co',result['answer'])
        self.assertNotIn('Data Scientist',result['answer'])


    def test_irrelevant_malformed_entry_does_not_poison_verified_latest_job(self):
        records=[self.record('Misspelled Employer','2018','2020'),self.record('Healthcare Co','11/2022','03/2025')]
        result=self.resolve('WORK EXPERIENCE Work Student Healthcare Co 11/2022 - 03/2025.',records,'recent employement')
        self.assertIn('Work Student at Healthcare Co',result['answer'])

    def test_citations_are_resolved_from_verified_text_not_model_number_guess(self):
        sources=[{'id':'1','document_id':1,'chunk_id':1,'position':0,'excerpt':'WORK EXPERIENCE Work Student Healthcare Co 11/2022 - 03/2025.'},
                 {'id':'2','document_id':1,'chunk_id':2,'position':1,'excerpt':'EDUCATION University 2022 - 2026.'}]
        record={**self.record('Healthcare Co','11/2022','03/2025'),'role':'Student','source_ids':['2']}
        result=json.loads(resolve_latest_employer(json.dumps({'employment_history':[record]}),sources,'recent employement'))
        self.assertIn('Work Student at Healthcare Co',result['answer'])
        self.assertEqual(result['source_ids'],['1'])
