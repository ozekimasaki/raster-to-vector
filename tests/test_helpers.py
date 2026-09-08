"""Offline behavioral tests. python -m unittest discover -s tests -v"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import numpy as np
from PIL import Image, ImageCms
from r2v_lib.images import analyze, compare, load_image, propose
from r2v_lib.svg import inspect, path_segments
from r2v_lib.render import render


class Helpers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r2v 日本語 space ')
        self.dir = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def png(self, name, color=(200,30,70,255), size=(16,16)):
        p = self.dir/name; Image.new('RGBA', size, color).save(p); return p

    def svg(self, body, attrs='width="16" height="16" viewBox="0 0 16 16"'):
        p = self.dir/'test.svg'; p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{body}</svg>', encoding='utf-8'); return p

    def test_identity_premultiplied_metrics(self):
        a = self.png('a.png'); result = compare(a,a,self.dir/'compare')
        self.assertEqual(result['metrics']['premultiplied_rgb_max'],0)
        self.assertEqual(result['quality_status'],'indeterminate')

    def test_transparent_hidden_rgb_ignored(self):
        a=self.png('a.png',(255,0,0,0)); b=self.png('b.png',(0,255,0,0))
        result=compare(a,b,self.dir/'compare')
        self.assertEqual(result['metrics']['premultiplied_rgb_max'],0)
        self.assertIsNone(result['metrics']['silhouette_iou'])

    def test_alpha_deficit_and_excess(self):
        a=self.png('a.png',(200,30,70,128)); b=self.png('b.png',(200,30,70,255))
        r=compare(a,b,self.dir/'c')['metrics']
        self.assertGreater(r['alpha_max_excess'],.49)
        self.assertEqual(r['alpha_max_deficit'],0)

    def test_wrong_color_not_hidden_by_alpha(self):
        a=self.png('a.png'); b=self.png('b.png',(0,255,0,255))
        r=compare(a,b,self.dir/'c')['metrics']
        self.assertEqual(r['alpha_mae'],0); self.assertGreater(r['premultiplied_rgb_max'],.8)

    def test_size_mismatch_not_rescaled(self):
        a=self.png('a.png'); b=self.png('b.png',size=(8,8))
        with self.assertRaises(ValueError): compare(a,b,self.dir/'c')

    def test_quantization_preserves_alpha_and_holes(self):
        a=np.zeros((16,16,4),dtype=np.uint8); a[:,:,:3]=[80,120,170]; a[:,:,3]=np.arange(16)*17
        p=self.dir/'a.png'; Image.fromarray(a).save(p)
        propose(p,self.dir/'q',8)
        q=np.asarray(Image.open(self.dir/'q/regions.png'))
        np.testing.assert_array_equal(q[:,:,3],a[:,:,3])
        labels=np.load(self.dir/'q/labels.npy',allow_pickle=False)
        self.assertTrue((labels[:,0]==-1).all())

    def test_fully_transparent_regions(self):
        r=propose(self.png('a.png',(1,2,3,0)),self.dir/'q',32)
        self.assertEqual(r['palette_rgb'],[])

    def test_exif_orientation(self):
        p=self.dir/'exif.jpg'; exif=Image.Exif(); exif[274]=6
        Image.new('RGB',(10,20)).save(p,exif=exif)
        im,meta=load_image(p); self.assertEqual(im.size,(20,10)); self.assertEqual(meta['exif_orientation'],6)

    def test_valid_and_invalid_icc(self):
        p=self.dir/'icc.png'; icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.new('RGB',(4,4)).save(p,icc_profile=icc)
        self.assertEqual(load_image(p)[1]['color_management'],'ICC_converted_to_sRGB')
        Image.new('RGB',(4,4)).save(p,icc_profile=b'not-an-icc')
        with self.assertRaises(ValueError): load_image(p)

    def test_multiframe_requires_choice(self):
        p=self.dir/'anim.webp'
        Image.new('RGB',(8,8),'red').save(p,save_all=True,append_images=[Image.new('RGB',(8,8),'blue')],duration=100,loop=0)
        with self.assertRaises(ValueError): load_image(p)
        self.assertEqual(load_image(p,1)[1]['frame'],1)

    def test_corrupt_image_cli(self):
        p=self.dir/'bad.png'; p.write_bytes(b'bad')
        r=subprocess.run([sys.executable,str(ROOT/'scripts/r2v.py'),'analyze',str(p),'--out',str(self.dir/'out')],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(r.returncode,2); self.assertEqual(json.loads(r.stdout)['status'],'failed')

    def test_safe_gradient_clip(self):
        p=self.svg('<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient><clipPath id="c"><circle cx="8" cy="8" r="5"/></clipPath></defs><rect width="16" height="16" fill="url(#g)" clip-path="url(#c)"/>')
        self.assertEqual(inspect(p)[0]['status'],'passed')

    def test_crisp_aa_fixture_inspects_without_use(self):
        for name in ('two_rects_normal','two_rects_base_fill','two_rects_crisp_aa'):
            status=inspect(ROOT/f'examples/fixtures/{name}.svg')[0]['status']
            self.assertEqual(status,'passed',name)
        self.assertEqual(inspect(self.svg('<defs><g id="faces"><rect width="8" height="8"/></g></defs><use href="#faces"/>'))[0]['status'],'failed')

    def test_inert_cfvx_metadata(self):
        p=self.svg('<g data-cfvx-role="fill"><path d="M0 0L1 1Z"/></g>')
        self.assertEqual(inspect(p)[0]['status'],'passed')

    def test_external_and_active_svg_rejected(self):
        cases=['<script>alert(1)</script>','<image href="data:image/png;base64,AA=="/>',
               '<foreignObject/>','<use href="#x"/>','<rect onload="alert(1)"/>',
               '<style>@import "https://example.com";</style>', '<rect fill="url(https://example.com/a)"/>',
               '<rect style="fill:u\\72l(https://example.com)"/>','<rect style="fill:var(--paint)"/>',
               '<rect style="cursor:url(file:///secret)"/>']
        for body in cases:
            with self.subTest(body=body): self.assertEqual(inspect(self.svg(body))[0]['status'],'failed')

    def test_duplicate_missing_wrong_reference(self):
        for body in ['<g id="x"/><g id="x"/>','<rect fill="url(#missing)"/>','<g id="x"/><rect fill="url(#x)"/>']:
            self.assertEqual(inspect(self.svg(body))[0]['status'],'failed')

    def test_numeric_path_rejections(self):
        for body in ['<path d="M 0 0 L 1"/>','<path d="M 0 0 A 1 1 0 3 0 2 2"/>','<rect width="NaN"/>','<circle r="-1"/>']:
            self.assertEqual(inspect(self.svg(body))[0]['status'],'failed')
        self.assertEqual(path_segments('M0 0C1 2 3 4 5 6Z'),3)

    def test_dtd_rejected(self):
        p=self.dir/'entity.svg'; p.write_text('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///test">]><svg/>')
        self.assertEqual(inspect(p)[0]['status'],'failed')

    def test_topology_not_certified(self):
        r,_=inspect(self.svg('<path d="M0 0L16 16L0 16L16 0Z"/>'))
        self.assertEqual(r['status'],'passed'); self.assertEqual(r['topology'],'indeterminate')

    def test_no_renderer_preserves_indeterminate(self):
        p=self.svg('<rect width="16" height="16"/>')
        failure=subprocess.CompletedProcess([],3,'{"error":"missing"}','')
        with patch('r2v_lib.render.run_bounded',return_value=failure):
            with self.assertRaises(RuntimeError): render(p,self.dir/'r')
        self.assertEqual(json.loads((self.dir/'r/render.json').read_text())['status'],'indeterminate')

    def test_chromium_failure_falls_back_with_evidence(self):
        p=self.svg('<rect width="16" height="16"/>')
        first=subprocess.CompletedProcess([],3,'missing','')
        second=subprocess.CompletedProcess([],0,'{"status":"passed","renderer":"cairosvg"}','')
        with patch('r2v_lib.render.run_bounded',side_effect=[first,second]): result=render(p,self.dir/'r')
        self.assertEqual(result['renderer'],'cairosvg'); self.assertEqual(len(result['failed_attempts']),1)

    def test_chromium_only(self):
        p=self.svg('<rect width="16" height="16"/>')
        success=subprocess.CompletedProcess([],0,'{"status":"passed","renderer":"chromium"}','')
        with patch('r2v_lib.render.run_bounded',return_value=success) as call: result=render(p,self.dir/'r')
        self.assertEqual(result['renderer'],'chromium'); self.assertEqual(call.call_count,1)

    def test_worker_timeout(self):
        from r2v_lib.processes import run_bounded
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable,'-c','import time; time.sleep(10)'],timeout=.2)


if __name__=='__main__': unittest.main()
