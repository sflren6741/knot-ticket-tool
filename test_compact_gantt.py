"""Compact chrome and calendar-scale acceptance checks."""
import unittest
import test_interactions as base


class CompactGantt(unittest.TestCase):
    js=base.TicketInteractions.js
    select=base.TicketInteractions.select
    card=base.TicketInteractions.card
    setUp=base.TicketInteractions.setUp
    tearDown=base.TicketInteractions.tearDown

    @classmethod
    def setUpClass(cls):
        base.TicketInteractions.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        base.TicketInteractions.tearDownClass.__func__(cls)

    def test_63_compact_two_rows_at_desktop_widths(self):
        self.assertEqual(self.page.locator('.breadcrumb,.topbar,.canvas-head,#table-toggle,#schedule-table-wrap').count(),0)
        for width in [1920,1600,1100,980]:
            self.page.set_viewport_size({'width':width,'height':1000})
            self.assertAlmostEqual(self.page.locator('#canvas-scroll').bounding_box()['y'],100,delta=1)
            row=self.page.locator('.commandbar').bounding_box()
            for selector in ['#new-button','#new-memo','#arrange-button','#fit-button','#undo-button','#redo-button','#workspace-menu > summary','#help-button']:
                box=self.page.locator(selector).bounding_box()
                self.assertGreaterEqual(box['x'],row['x'])
                self.assertLessEqual(box['x']+box['width'],row['x']+row['width']+1)
                self.assertGreaterEqual(box['y'],row['y'])
                self.assertLessEqual(box['y']+box['height'],row['y']+row['height'])
            tabs=self.page.locator('#tab-tickets').bounding_box()
            focus=self.page.locator('[data-focus="overdue"]').bounding_box()
            self.assertAlmostEqual(tabs['y']+tabs['height']/2,focus['y']+focus['height']/2,delta=1)
            self.assertLessEqual(focus['x']+focus['width'],self.page.locator('.details').bounding_box()['x'])

    def test_64_workspace_zoom_and_legend_menus(self):
        before=self.js('snapshot()')
        self.assertFalse(self.page.locator('#open-workspace').is_visible())
        self.page.locator('#workspace-menu > summary').click()
        self.assertTrue(self.page.locator('#open-workspace').is_visible())
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('#open-workspace').is_visible())
        zoom=self.js('zoom')
        self.page.locator('#zoom-menu > summary').click()
        self.page.locator('#zoom-in').click()
        self.assertGreater(self.js('zoom'),zoom)
        self.page.locator('#help-button').click()
        self.assertFalse(self.js("$('zoom-menu').open"))
        self.page.locator('#close-help').click()
        self.page.locator('#canvas-legend > summary').click()
        self.assertTrue(self.page.locator('.legend-popup').is_visible())
        self.page.keyboard.press('Escape')
        self.assertFalse(self.page.locator('.legend-popup').is_visible())
        self.assertEqual(self.js('snapshot()'),before)

    def test_65_week_and_calendar_month_boundaries(self):
        ranges=self.js("""()=>{
         const items=[{start:'2026-12-30',due:'2027-01-08'}],m=ganttRange([{start:'2028-02-27',due:'2028-03-02'}],'month'),w=ganttRange(items,'week'),d=ganttRange(items,'day');
         return {weekFirst:w.iso(w.first),weekEnd:w.iso(w.end-1),weekLengths:w.periods.map(p=>p.end-p.first),monthFirst:m.iso(m.first),monthLengths:m.periods.map(p=>p.end-p.first),daySpan:d.span};
        }""")
        self.assertEqual(ranges['weekFirst'],'2026-12-28')
        self.assertEqual(ranges['weekEnd'],'2027-01-24')
        self.assertEqual(ranges['weekLengths'],[7]*4)
        self.assertEqual(ranges['monthFirst'],'2028-02-01')
        self.assertEqual(ranges['monthLengths'],[29,31,30,31])
        self.assertEqual(ranges['daySpan'],14)

    def test_66_scale_preserves_data_selection_focus_and_dates(self):
        self.page.locator('#tab-schedule').click()
        self.page.locator('[data-focus="soon"]').click()
        before=self.js('({data:snapshot(),selected:[...selected],focusMode,undo:undoStack.length})')
        widths=[]
        for scale in ['day','week','month']:
            self.page.locator(f'button[data-scale="{scale}"]').click()
            self.assertEqual(self.js('({data:snapshot(),selected:[...selected],focusMode,undo:undoStack.length})'),before)
            self.assertEqual(self.page.locator('.gantt-row').count(),7)
            self.assertTrue(self.page.locator('.gantt-row[data-row="WEB-002"]').evaluate("el=>el.classList.contains('selected')"))
            self.assertEqual(self.page.locator('button[data-scale][aria-pressed="true"]').get_attribute('data-scale'),scale)
            geometry=self.js("()=>{const t=getTicket('WEB-002'),b=document.querySelector('.gantt-bar[data-ticket=\"WEB-002\"]');return {start:scheduleRange.first+parseFloat(b.style.left)/100*scheduleRange.span,duration:parseFloat(b.style.width)/100*scheduleRange.span,expected:dayNumber(t.start),days:dayNumber(t.due)-dayNumber(t.start)+1};}")
            self.assertAlmostEqual(geometry['start'],geometry['expected'],places=3)
            self.assertAlmostEqual(geometry['duration'],geometry['days'],places=4)
            widths.append(self.page.locator('.gantt-bar[data-ticket="WEB-002"]').bounding_box()['width'])
        self.assertGreater(widths[0],widths[1])
        self.assertGreater(widths[1],widths[2])
        self.assertEqual(self.page.locator('#table-toggle,.schedule-table').count(),0)

    def test_67_scale_memory_keyboard_and_reload_default(self):
        self.page.locator('#tab-schedule').click()
        self.assertEqual(self.js('ganttScale'),'day')
        self.page.locator('button[data-scale="day"]').focus()
        self.page.keyboard.press('ArrowRight')
        self.assertEqual(self.js('ganttScale'),'week')
        self.page.keyboard.press('End')
        self.assertEqual(self.js('ganttScale'),'month')
        self.page.locator('#tab-tickets').click()
        self.page.locator('#tab-schedule').click()
        self.assertEqual(self.js('ganttScale'),'month')
        self.page.reload()
        self.assertEqual(self.js('ganttScale'),'day')

    def test_68_empty_and_memo_only_schedules(self):
        self.js("restore({version:2,tickets:[],dependencies:[],projects:{all:'All',website:'Empty'},groups:[],references:[]});renderAll()")
        self.page.locator('#tab-schedule').click()
        for scale in ['day','week','month']:
            self.page.locator(f'button[data-scale="{scale}"]').click()
            self.assertEqual(self.page.locator('.gantt-row').count(),0)
            self.assertGreater(self.page.locator('.gantt-day').count(),0)
        self.js('newMemo()')
        self.assertEqual(self.page.locator('.gantt-row').count(),0)
        self.assertEqual(self.page.locator('.schedule-memos button').count(),1)

    def test_69_long_range_bounded_labels_and_calendar_positions(self):
        self.js("getTicket('WEB-001').start='1900-01-01';getTicket('WEB-001').due='2100-12-31';renderAll()")
        self.page.locator('#tab-schedule').click()
        for scale in ['day','week','month']:
            self.page.locator(f'button[data-scale="{scale}"]').click()
            self.assertLessEqual(self.page.locator('.gantt-day').count(),400)
            self.assertEqual(self.page.locator('.period-grid').count(),1)
            self.assertGreater(self.page.locator('.period-line').count(),0)
            self.assertTrue(self.js('Number.isFinite(scheduleRange.span)&&scheduleRange.span>0'))
            self.assertLessEqual(self.page.locator('.gantt').bounding_box()['width'],1200241)

    def test_70_month_view_date_edit_and_tooltips(self):
        self.page.locator('#tab-schedule').click()
        self.page.locator('button[data-scale="month"]').click()
        self.page.locator('#detail-due').fill('2027-04-08')
        self.page.locator('#detail-due').press('Tab')
        self.assertEqual(self.js('ganttScale'),'month')
        self.page.locator('.gantt-bar[data-ticket="WEB-002"]').focus()
        self.assertIn('2027-04-08',self.page.locator('#tooltip').inner_text())
        self.assertGreater(self.page.locator('.gantt-day').count(),4)


class ScalePersistence(unittest.TestCase):
    js=base.TicketInteractions.js
    select=base.TicketInteractions.select
    card=base.TicketInteractions.card
    setUp=base.TicketInteractions.setUp
    tearDown=base.TicketInteractions.tearDown
    workspace=base.WorkspacePersistence.workspace
    read=base.WorkspacePersistence.read

    @classmethod
    def setUpClass(cls):
        base.WorkspacePersistence.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        base.WorkspacePersistence.tearDownClass.__func__(cls)

    def test_71_view_controls_do_not_dirty_saved_workspace(self):
        self.workspace()
        self.select('WEB-002')
        revision=self.js('Workspace.revision')
        before=self.read('workspace.json')
        self.page.locator('#tab-schedule').click()
        self.page.locator('button[data-scale="week"]').click()
        self.page.locator('button[data-scale="month"]').click()
        self.page.locator('[data-focus="ready"]').click()
        self.page.wait_for_timeout(600)
        self.assertEqual(self.js('Workspace.phase'),'saved')
        self.assertEqual(self.js('Workspace.revision'),revision)
        self.assertEqual(self.read('workspace.json'),before)
        self.assertEqual(self.js('selectedId'),'WEB-002')


if __name__=='__main__':
    unittest.main(verbosity=2)
