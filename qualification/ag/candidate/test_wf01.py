"""WF-01: real unchanged signals and full persisted effect oracles."""
import unittest, uuid
from django.utils import timezone
from actions.models import Plan
from test_workflow import WorkflowTests
from gestion_joueurs.models import Video, VideoStatusHistory, Notification
from client_portal.models import VideoWorkflow, VideoActivity

MODELS={'history':VideoStatusHistory,'activities':VideoActivity,'notifications':Notification}
FIELDS={'history':('status','editor_id','created_by_id','comment'), 'activities':('kind','visibility','message','metadata','created_by_id'), 'notifications':('user_id','message','notification_type','video_id','player_id','sent_by_id','is_read')}

def business_rows(video):
    return {name:list(model.objects.filter(**({'pk':video} if name=='video' else {'video_id':video})).order_by('pk').values()) for name,model in {'video':Video,'workflow':VideoWorkflow,**MODELS}.items()}

def assert_effects(test, plan, result, before):
    """Check all inserted rows, not only IDs claimed by the effect recorder."""
    previews=plan.snapshots['__preview__']['transitions']
    for name,model in MODELS.items():
        expected=[row for p in previews for row in p[name]]
        actual=[];new_ids=[]
        for preview in previews:
            pk=preview['id']; old={row['id'] for row in before[pk][name]}
            qs=model.objects.filter(video_id=pk).exclude(pk__in=old).order_by('pk')
            new_ids.extend(qs.values_list('pk',flat=True)); actual.extend(qs.values(*FIELDS[name]))
            # Also disallow deletion or alteration of pre-existing rows.
            test.assertEqual(list(model.objects.filter(pk__in=old).order_by('pk').values()),before[pk][name])
        canonical=lambda rows: sorted(rows,key=lambda r:__import__('json').dumps(r,sort_keys=True,default=str))
        test.assertEqual(len(actual),len(expected),name+' count versus preview')
        test.assertEqual(canonical(actual),canonical(expected),name+' complete rows versus preview')
        test.assertEqual(sorted(new_ids),sorted(result['effects'][name]),name+' recorded IDs versus all inserts')
    for p in previews:
        test.assertEqual(Video.objects.get(pk=p['id']).status,p['newStatus'])
        w=VideoWorkflow.objects.filter(video_id=p['id']).values('stage','priority','progress','next_action','blocked_reason').first()
        test.assertEqual(w,p['newWorkflow'])

class WF01Tests(unittest.TestCase):
    setUp=WorkflowTests.setUp
    steps=WorkflowTests.steps
    def tie(self, same_status=False, older=False):
        qs=VideoStatusHistory.objects.filter(video=self.video)
        qs.update(status='pending' if same_status else 'in_progress')
        h=VideoStatusHistory.objects.create(video=self.video,status='pending',editor=self.ve)
        stamp=timezone.now()
        qs.update(changed_at=stamp)
        if older:
            from datetime import timedelta
            qs.update(changed_at=stamp-timedelta(days=1))
            VideoStatusHistory.objects.create(video=self.video,status='pending',editor=self.ve)
    def test_prepare_ambiguous_latest_history_refused_before_preview(self):
        from unittest.mock import patch
        from actions.workflow import ProductionTransition
        self.tie(); before=business_rows(self.video.pk); plans=Plan.objects.count()
        with patch.object(ProductionTransition,'preview',side_effect=AssertionError('ambiguous preview reached')):
            with self.assertRaisesRegex(ValueError,'workflow_history_ambiguous'):
                self.engine.prepare(uuid.uuid4().hex,self.steps())
        self.assertEqual(business_rows(self.video.pk),before)
        self.assertEqual(Plan.objects.count(),plans)
    def test_tie_added_between_prepare_execute_is_refused_without_business_mutation(self):
        p=self.engine.prepare(uuid.uuid4().hex,self.steps())
        self.tie(); before=business_rows(self.video.pk)
        with self.assertRaisesRegex(ValueError,'workflow_history_ambiguous'):self.engine.execute(p['id'])
        self.assertEqual(business_rows(self.video.pk),before)
        plan=Plan.objects.get(pk=p['id']);self.assertEqual(plan.state,'prepared');self.assertEqual(plan.effects,{})
    def test_same_status_latest_tie_also_closed(self):
        self.tie(same_status=True)
        with self.assertRaisesRegex(ValueError,'workflow_history_ambiguous'):self.engine.prepare(uuid.uuid4().hex,self.steps())
    def test_older_tie_with_unique_latest_preserves_real_signal(self):
        self.tie(older=True)
        before={self.video.pk:business_rows(self.video.pk)}
        p=self.engine.prepare(uuid.uuid4().hex,self.steps())
        plan=Plan.objects.get(pk=p['id']);r=self.engine.execute(p['id'])
        self.assertEqual(r['state'],'succeeded');assert_effects(self,plan,r,before)
    def test_effect_oracle_rejects_unrecorded_extra_history(self):
        before={self.video.pk:business_rows(self.video.pk)}
        p=self.engine.prepare(uuid.uuid4().hex,self.steps());plan=Plan.objects.get(pk=p['id'])
        r=self.engine.execute(p['id']);assert_effects(self,plan,r,before)
        VideoStatusHistory.objects.create(video=self.video,status='in_progress',editor=self.ve)
        with self.assertRaisesRegex(AssertionError,'history count versus preview'):assert_effects(self,plan,r,before)
    def test_effect_oracle_rejects_missing_history(self):
        before={self.video.pk:business_rows(self.video.pk)}
        p=self.engine.prepare(uuid.uuid4().hex,self.steps());plan=Plan.objects.get(pk=p['id'])
        r=self.engine.execute(p['id']);VideoStatusHistory.objects.filter(pk__in=r['effects']['history']).delete()
        with self.assertRaisesRegex(AssertionError,'history count versus preview'):assert_effects(self,plan,r,before)
