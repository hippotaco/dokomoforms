"""Model tests"""
import json
import datetime
from decimal import Decimal

from tests.util import DokoTest, setUpModule, tearDownModule
utils = (setUpModule, tearDownModule)

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, DataError

from psycopg2.extras import NumericRange, DateRange, DateTimeTZRange

import dokomoforms.models as models
import dokomoforms.exc as exc
from dokomoforms.models.survey import Bucket


class TestUser(DokoTest):
    def test_to_json(self):
        with self.session.begin():
            new_user = models.User(name='a')
            new_user.emails = [models.Email(address='b')]
            self.session.add(new_user)
        user = self.session.query(models.User).one()
        self.assertEqual(
            json.loads(user._to_json()),
            {
                'id': user.id,
                'deleted': False,
                'name': 'a',
                'emails': ['b'],
                'role': 'enumerator',
                'last_update_time': user.last_update_time.isoformat(),
            }
        )

    def test_deleting_user_clears_email(self):
        with self.session.begin():
            new_user = models.User(name='a')
            new_user.emails = [models.Email(address='b')]
            self.session.add(new_user)
        self.assertEqual(
            self.session.query(func.count(models.Email.id)).scalar(),
            1
        )
        with self.session.begin():
            self.session.delete(self.session.query(models.User).one())
        self.assertEqual(
            self.session.query(func.count(models.Email.id)).scalar(),
            0
        )

    def test_email_identifies_one_user(self):
        """No duplicate e-mail address allowed."""
        with self.assertRaises(IntegrityError):
            with self.session.begin():
                user_a = models.User(name='a')
                user_a.emails = [models.Email(address='a')]
                self.session.add(user_a)

                user_b = models.User(name='b')
                user_b.emails = [models.Email(address='a')]
                self.session.add(user_b)


class TestNode(DokoTest):
    def test_non_instantiable(self):
        self.assertRaises(TypeError, models.Node)

    def test_construct_node(self):
        with self.session.begin():
            self.session.add(models.construct_node(
                type_constraint='text',
                title='test'
            ))
        sn = self.session.query(models.Node).one()
        self.assertEqual(sn.title, 'test')
        question = self.session.query(models.Question).one()
        self.assertEqual(question.title, 'test')

    def test_construct_node_wrong_type(self):
        self.assertRaises(
            exc.NoSuchNodeTypeError,
            models.construct_node, type_constraint='wrong'
        )

    def test_construct_node_all_types(self):
        with self.session.begin():
            for node_type in models.NODE_TYPES:
                self.session.add(models.construct_node(
                    type_constraint=node_type,
                    title='test_' + node_type,
                ))
        self.assertEqual(
            self.session.query(func.count(models.Node.id)).scalar(),
            11,
        )
        self.assertEqual(
            self.session.query(func.count(models.Note.id)).scalar(),
            1,
        )
        self.assertEqual(
            self.session.query(func.count(models.Question.id)).scalar(),
            10,
        )


class TestQuestion(DokoTest):
    def test_non_instantiable(self):
        self.assertRaises(TypeError, models.Question)


class TestChoice(DokoTest):
    def test_automatic_numbering(self):
        with self.session.begin():
            q = models.construct_node(
                title='test_automatic_numbering',
                type_constraint='multiple_choice',
            )
            q.choices = [models.Choice(choice_text=str(i)) for i in range(3)]
            self.session.add(q)
        question = self.session.query(models.MultipleChoiceQuestion).one()
        choices = self.session.query(models.Choice).order_by(
            models.Choice.choice_number).all()
        self.assertEqual(question.choices, choices)
        self.assertEqual(choices[0].choice_number, 0)
        self.assertEqual(choices[1].choice_number, 1)
        self.assertEqual(choices[2].choice_number, 2)

    def test_question_delete_cascades_to_choices(self):
        with self.session.begin():
            q = models.construct_node(
                title='test_question_delete_cascades_to_choices',
                type_constraint='multiple_choice',
            )
            q.choices = [models.Choice(choice_text='deleteme')]
            self.session.add(q)
        self.assertEqual(
            self.session.query(func.count(models.Choice.id)).scalar(),
            1
        )
        with self.session.begin():
            self.session.delete(
                self.session.query(models.MultipleChoiceQuestion).one()
            )
        self.assertEqual(
            self.session.query(func.count(models.Choice.id)).scalar(),
            0
        )

    def test_wrong_question_type(self):
        with self.session.begin():
            q = models.construct_node(
                title='test_wrong_question_type',
                type_constraint='text',
            )
            q.choices = [models.Choice(choice_text='should not show up')]
            self.session.add(q)
        self.assertEqual(
            self.session.query(func.count(models.Choice.id)).scalar(),
            0
        )


class TestSurvey(DokoTest):
    def test_one_node_surveys(self):
        number_of_questions = 11
        with self.session.begin():
            creator = models.SurveyCreator(
                name='creator',
                emails=[models.Email(address='email')],
            )
            node_types = list(models.NODE_TYPES)
            for node_type in node_types:
                survey = models.Survey(
                    title=node_type + '_survey',
                    nodes=[
                        models.SurveyNode(
                            node=models.construct_node(
                                type_constraint=node_type,
                                title=node_type + '_node',
                            ),
                        ),
                    ],
                )
                creator.surveys.append(survey)
            self.session.add(creator)

        the_creator = self.session.query(models.SurveyCreator).one()
        self.assertEqual(
            len(the_creator.surveys),
            number_of_questions,
            msg='not all {} surveys were created'.format(number_of_questions)
        )
        self.assertListEqual(
            [the_creator.surveys[n].nodes[0].type_constraint
                for n in range(number_of_questions)],
            node_types,
            msg='the surveys were not created in the right order'
        )
        self.assertListEqual(
            [len(the_creator.surveys[n].nodes)
                for n in range(number_of_questions)],
            [1] * number_of_questions,
            msg='there is a survey with more than one node'
        )


class TestBucket(DokoTest):
    def _create_blank_survey(self) -> (models.SurveyCreator, models.Survey):
        creator = models.SurveyCreator(
            name='creator',
            emails=[models.Email(address='email')],
        )
        survey = models.Survey(title='TestBucket')
        creator.surveys = [survey]
        return creator, survey

    def test_integer_bucket(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            survey.nodes = [
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='integer',
                        title='node',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='integer',
                                    bucket='(1, 2]'
                                ),
                            ],
                        ),
                    ],
                ),
            ]
            self.session.add(creator)

        the_bucket = self.session.query(Bucket).one()
        self.assertEqual(the_bucket.bucket, NumericRange(2, 3, '[)'))

    def test_integer_incorrect_bucket_type(self):
        with self.assertRaises(IntegrityError):
            with self.session.begin():
                creator, survey = self._create_blank_survey()
                survey.nodes = [
                    models.SurveyNode(
                        node=models.construct_node(
                            type_constraint='integer',
                            title='node',
                        ),
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='decimal',
                                        bucket='(1.3, 2.3]'
                                    ),
                                ],
                            ),
                        ],
                    ),
                ]
                self.session.add(creator)

    def test_integer_incorrect_range(self):
        """A decimal is not an integer"""
        with self.assertRaises(DataError):
            with self.session.begin():
                creator, survey = self._create_blank_survey()
                survey.nodes = [
                    models.SurveyNode(
                        node=models.construct_node(
                            type_constraint='integer',
                            title='node',
                        ),
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='integer',
                                        bucket='(1.3, 2.3]'
                                    ),
                                ],
                            ),
                        ],
                    ),
                ]
                self.session.add(creator)

    def test_integer_two_buckets(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            survey.nodes = [
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='integer',
                        title='node',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='integer',
                                    bucket='(1, 2]'
                                ),
                                models.construct_bucket(
                                    bucket_type='integer',
                                    bucket='(4, 6]'
                                ),
                            ],
                        ),
                    ],
                ),
            ]
            self.session.add(creator)

        self.assertEqual(self.session.query(func.count(Bucket.id)).scalar(), 2)

    def test_integer_bucket_no_overlap(self):
        """The range [,] covers all integers, so (-2, 6] overlaps."""
        with self.assertRaises(IntegrityError):
            with self.session.begin():
                creator, survey = self._create_blank_survey()
                survey.nodes = [
                    models.SurveyNode(
                        node=models.construct_node(
                            type_constraint='integer',
                            title='node',
                        ),
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='integer',
                                        bucket='[,]'
                                    ),
                                    models.construct_bucket(
                                        bucket_type='integer',
                                        bucket='(-2, 6]'
                                    ),
                                ],
                            ),
                        ],
                    ),
                ]
                self.session.add(creator)

    def test_integer_bucket_no_overlap_different_sub_surveys(self):
        """
        Different SubSurveys belonging to the same SurveyNode cannot have
        overlapping buckets.
        """
        with self.assertRaises(IntegrityError):
            with self.session.begin():
                creator, survey = self._create_blank_survey()
                survey.nodes = [
                    models.SurveyNode(
                        node=models.construct_node(
                            type_constraint='integer',
                            title='node',
                        ),
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='integer',
                                        bucket='[1, 5]'
                                    ),
                                ],
                            ),
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='integer',
                                        bucket='[3, 7]'
                                    ),
                                ],
                            ),
                        ],
                    ),
                ]
                self.session.add(creator)

    def test_integer_bucket_no_empty_range(self):
        """There are no integers between 2 and 3 exclusive"""
        with self.assertRaises(IntegrityError):
            with self.session.begin():
                creator, survey = self._create_blank_survey()
                survey.nodes = [
                    models.SurveyNode(
                        node=models.construct_node(
                            type_constraint='integer',
                            title='node',
                        ),
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='integer',
                                        bucket='(2, 3)'
                                    ),
                                ],
                            ),
                        ],
                    ),
                ]
                self.session.add(creator)

    def test_integer_overlapping_buckets_different_nodes(self):
        """Nothing wrong with overlapping buckets on different nodes."""
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            survey.nodes = [
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='integer',
                        title='node1',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='integer',
                                    bucket='[1, 5]'
                                ),
                            ],
                        ),
                    ],
                ),
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='integer',
                        title='node2',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='integer',
                                    bucket='[3, 7]'
                                ),
                            ],
                        ),
                    ],
                ),
            ]
            self.session.add(creator)

        self.assertEqual(self.session.query(func.count(Bucket.id)).scalar(), 2)

    def test_decimal_bucket(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            survey.nodes = [
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='decimal',
                        title='node',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='decimal',
                                    bucket='(1.3, 2.3]'
                                ),
                            ],
                        ),
                    ],
                ),
            ]
            self.session.add(creator)

        the_bucket = self.session.query(Bucket).one()
        self.assertEqual(
            the_bucket.bucket,
            NumericRange(Decimal('1.3'), Decimal('2.3'), '(]'),
        )

    def test_date_bucket(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            survey.nodes = [
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='date',
                        title='node',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='date',
                                    bucket='(2015-1-1, 2015-2-2]'
                                ),
                            ],
                        ),
                    ],
                ),
            ]
            self.session.add(creator)

        the_bucket = self.session.query(Bucket).one()
        self.assertEqual(
            the_bucket.bucket,
            DateRange(
                datetime.date(2015, 1, 2), datetime.date(2015, 2, 3), '[)'
            ),
        )

    def test_time_bucket(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            survey.nodes = [
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='time',
                        title='node',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='time',
                                    bucket='(1:11, 2:22]'
                                ),
                            ],
                        ),
                    ],
                ),
            ]
            self.session.add(creator)

        the_bucket = self.session.query(Bucket).one()
        tzinfo = the_bucket.bucket.lower.tzinfo
        self.assertEqual(
            the_bucket.bucket,
            DateTimeTZRange(
                datetime.datetime(1970, 1, 1, 1, 11, tzinfo=tzinfo),
                datetime.datetime(1970, 1, 1, 2, 22, tzinfo=tzinfo),
                '(]'
            )
        )

    def test_time_bucket_all_valid_time_formats(self):
        valid_time_formats = [
            '[04:05:06.789, 04:05:06.790]',
            '[04:05:06, 04:05:07]',
            '[04:05, 04:06]',
            '[040506, 040507]',
            '[04:05 AM, 04:06 AM]',
            '[04:05 PM, 04:06 PM]',
            '[04:05:06.789-8, 04:05:06.790-8]',
            '[04:05:06-08:00, 04:05:07-08:00]',
            '[04:05-08:00, 04:06-08:00]',
            '[040506-08, 040507-08]',
            '[04:05:06 PST, 04:05:07 PST]',
            # Not sure if this is worth trying to parse...
            # '[2003-04-12 04:05:06 America/New_York,'
            # ' 2003-04-12 04:05:07 America/New_York]',
        ]
        with self.session.begin():
            creator = models.SurveyCreator(
                name='creator',
                emails=[models.Email(address='email')],
            )
            for i, time_format in enumerate(valid_time_formats):
                survey = models.Survey(title='Test {}'.format(i))
                creator.surveys.append(survey)
                survey.nodes = [
                    models.SurveyNode(
                        node=models.construct_node(
                            type_constraint='time',
                            title='node',
                        ),
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='time',
                                        bucket=time_format
                                    ),
                                ],
                            ),
                        ],
                    ),
                ]
            self.session.add(creator)

        self.assertEqual(
            self.session.query(func.count(Bucket.id)).scalar(),
            11
        )

    def test_timestamp_bucket(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            survey.nodes = [
                models.SurveyNode(
                    node=models.construct_node(
                        type_constraint='timestamp',
                        title='node',
                    ),
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='timestamp',
                                    bucket='(2015-1-1 1:11, 2015-1-1 2:22]'
                                ),
                            ],
                        ),
                    ],
                ),
            ]
            self.session.add(creator)

        the_bucket = self.session.query(Bucket).one()
        tzinfo = the_bucket.bucket.lower.tzinfo
        self.assertEqual(
            the_bucket.bucket,
            DateTimeTZRange(
                datetime.datetime(2015, 1, 1, 1, 11, tzinfo=tzinfo),
                datetime.datetime(2015, 1, 1, 2, 22, tzinfo=tzinfo),
                '(]'
            )
        )

    def test_multiple_choice_bucket(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            node = models.construct_node(
                type_constraint='multiple_choice', title='node'
            )
            choice = models.Choice()
            node.choices = [choice]

            survey.nodes = [
                models.SurveyNode(
                    node=node,
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='multiple_choice',
                                    bucket=choice
                                ),
                            ],
                        ),
                    ]
                ),
            ]
            self.session.add(creator)

        the_bucket = self.session.query(Bucket).one()
        the_choice = self.session.query(models.Choice).one()
        self.assertIs(the_bucket.bucket, the_choice)

    def test_multiple_choice_multiple_buckets(self):
        with self.session.begin():
            creator, survey = self._create_blank_survey()
            node = models.construct_node(
                type_constraint='multiple_choice', title='node'
            )
            choice1 = models.Choice()
            choice2 = models.Choice()
            node.choices = [choice1, choice2]

            survey.nodes = [
                models.SurveyNode(
                    node=node,
                    nodes=[
                        models.SubSurvey(
                            buckets=[
                                models.construct_bucket(
                                    bucket_type='multiple_choice',
                                    bucket=choice1
                                ),
                                models.construct_bucket(
                                    bucket_type='multiple_choice',
                                    bucket=choice2
                                ),
                            ],
                        ),
                    ]
                ),
            ]
            self.session.add(creator)

        bucket1 = self.session.query(Bucket).all()[0]
        choice1 = self.session.query(models.Choice).all()[0]
        self.assertIs(bucket1.bucket, choice1)

        bucket2 = self.session.query(Bucket).all()[1]
        choice2 = self.session.query(models.Choice).all()[1]
        self.assertIs(bucket2.bucket, choice2)

    def test_multiple_choice_bucket_no_overlap(self):
        with self.assertRaises(IntegrityError):
            with self.session.begin():
                creator, survey = self._create_blank_survey()
                node = models.construct_node(
                    type_constraint='multiple_choice', title='node'
                )
                choice = models.Choice()
                node.choices = [choice]

                survey.nodes = [
                    models.SurveyNode(
                        node=node,
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='multiple_choice',
                                        bucket=choice
                                    ),
                                    models.construct_bucket(
                                        bucket_type='multiple_choice',
                                        bucket=choice
                                    ),
                                ],
                            ),
                        ]
                    ),
                ]
                self.session.add(creator)

    def test_multiple_choice_bucket_choice_from_wrong_question(self):
        with self.assertRaises(IntegrityError):
            with self.session.begin():
                creator, survey = self._create_blank_survey()
                wrong_node = models.construct_node(
                    type_constraint='multiple_choice', title='wrong'
                )
                wrong_choice = models.Choice()
                wrong_node.choices = [wrong_choice]

                survey.nodes = [
                    models.SurveyNode(
                        node=models.construct_node(
                            type_constraint='multiple_choice',
                            title='node',
                            choices=[models.Choice()],
                        ),
                        nodes=[
                            models.SubSurvey(
                                buckets=[
                                    models.construct_bucket(
                                        bucket_type='multiple_choice',
                                        bucket=wrong_choice
                                    ),
                                ],
                            ),
                        ]
                    ),
                ]
                self.session.add(creator)