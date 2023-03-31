import os
import os.path
import pandas as pd
import sys
sys.path.append('..')
from src.utils.data import writePandas, getPandas

def imgRedir():
    
    raw_img_info = pd.read_csv(os.path.join('data', 'raw', 'img_data.csv'))
    image_meta = raw_img_info.rename(columns={'Image Data ID': 'IMG_ID', 'Subject': 'PATNO', 'Visit': 'EVENT_ID'})

    # Get image metadata file path
    xmllist = []
    for dirpath, dirnames, filenames in os.walk(os.path.join('data', 'raw', 'meta')):
        for filename in filenames:
            if dirpath == os.path.join('data', 'raw', 'meta'):
                continue
            xmllist.append(os.path.join(dirpath, filename))

    # Generate image dataframe by PATNO and IMG_ID
    data = []
    from xml.dom import minidom
    for xml in xmllist:
        root = minidom.parse(xml).documentElement
        subject = root.getElementsByTagName('subject')[0].getAttribute('id')
        study = root.getElementsByTagName('study')[0].getAttribute('uid')
        series = root.getElementsByTagName('series')[0].getAttribute('uid')
        image = root.getElementsByTagName('image')[0].getAttribute('uid')
        relative_path = os.path.join('data', 'raw', 'img', xml.split(os.sep)[3], xml.split(os.sep)[4], xml.split(os.sep)[5])
        nii_dir = os.listdir(relative_path)[0]
        nii_name = os.listdir(os.path.join(relative_path, nii_dir))[0]
        relative_path = os.path.join(relative_path, nii_dir, nii_name)
        data.append({'PATNO': int(subject), 'IMG_ID': str(image), 'SERIES': str(series), 'IMG_PATH': str(relative_path)})
    data = pd.DataFrame(data)

    data = pd.merge(data, image_meta, on=['PATNO', 'IMG_ID'], how='left')
    data = data[['PATNO', 'SERIES', 'IMG_ID', 'EVENT_ID', 'Group', 'Sex', 'Age', 'Acq Date', 'IMG_PATH']]
    data['KEY'] = data['PATNO'].astype(str) + data['EVENT_ID'].astype(str) + data['IMG_ID'].astype(str)
    
    writePandas('img_raw', data)
    
    return data


def mvRaw(meta):
    import shutil
    for index, row in meta.iterrows():
        print(row['KEY'])
        os.makedirs(os.path.join('data', 'subj', row['KEY'], 'raw'))
        shutil.copy(row['IMG_PATH'], os.path.join('data', 'subj', row['KEY'], 'raw', 'raw.nii'))
        


def preprocFSL():
    from nipype.pipeline.engine import Workflow, Node
    from nipype import Function
    import nipype.interfaces.fsl as fsl
    fsl.FSLCommand.set_default_output_type('NIFTI')
    import nipype.interfaces.utility as util
    from nipype.interfaces.fsl import BET, FAST, ApplyMask
    from nipype.interfaces.ants import RegistrationSynQuick
    from nipype.interfaces.spm import Smooth
    import nipype.interfaces.io as nio
    
    data = getPandas('pat_data')

    def gm_extract(pve_files):
        return pve_files[1]

    key_list = data['KEY'].tolist()

    wf = Workflow(name='preproc', base_dir=os.path.abspath('tmp'))

    info_src = Node(util.IdentityInterface(fields=['key']), name='info_src')
    info_src.iterables = ('key', key_list)

    raw_src = Node(nio.DataGrabber(infields=['key'], outfields=['raw']), name='raw_src')
    raw_src.inputs.base_directory = os.path.abspath(os.path.join('data', 'subj'))
    raw_src.inputs.sort_filelist = False
    raw_src.inputs.template = '*'
    raw_src.inputs.template_args = {
        'raw': [['key']]
    }
    raw_src.inputs.field_template = {
        'raw': os.path.join('%s', 'raw', 'raw.nii')
    }

    bet = Node(BET(), name='bet')
    bet.inputs.robust = True

    reg = Node(RegistrationSynQuick(), name='reg')
    reg.inputs.fixed_image = os.path.abspath(os.path.join('data', 'bin', 'template.nii.gz'))
    reg.inputs.num_threads = 16

    fslseg = Node(FAST(), name='fslseg')
    fslseg.inputs.output_type = 'NIFTI'
    fslseg.inputs.segments = True
    fslseg.inputs.probability_maps = True
    fslseg.inputs.number_classes = 3

    gmextract = Node(Function(input_names=['pve_files'], output_names=['gm_file'], function=gm_extract), name='gmextract')

    smooth = Node(Smooth(), name='smooth')
    smooth.inputs.fwhm = 4

    msk = Node(ApplyMask(), name='msk')
    msk.inputs.mask_file = os.path.abspath(os.path.join('data', 'bin', 'mask.nii'))

    sinker = Node(nio.DataSink(infields=['key']), name='sinker')
    sinker.inputs.base_directory = os.path.abspath(os.path.join('data', 'subj'))
    # bet_replace = [('_bet'+str(i), os.path.join(key_list[i], 'preproc', 'fsl')) for i in range(len(key_list))]
    # reg_replace = [('_reg'+str(i), os.path.join(key_list[i], 'preproc', 'fsl')) for i in range(len(key_list))]
    # fslseg_replace = [('_fslseg'+str(i), os.path.join(key_list[i], 'preproc', 'fsl')) for i in range(len(key_list))]
    # msk_replace = [('_msk'+str(i), os.path.join(key_list[i], 'preproc', 'fsl')) for i in range(len(key_list))]
    # substitutions = [
    #     ('raw_brain', 'brain'),
    #     ('transformWarped', 'reg'),
    #     ('pve_0', 'csf'),
    #     ('pve_1', 'gm'),
    #     ('pve_2', 'wm'),
    # ]
    # sinker.inputs.regexp_substitutions = bet_replace + reg_replace + fslseg_replace + msk_replace + substitutions
    sinker.inputs.regexp_substitutions = [
        ('raw_brain', 'brain'),
        ('transformWarped', 'reg'),
        ('pve_0', 'csf'),
        ('pve_1', 'gm'),
        ('pve_2', 'wm'),
        ('_key_', ''),
    ]

    wf.connect([
        (info_src, raw_src, [('key', 'key')]),
        (raw_src, bet, [('raw', 'in_file')]),
        (bet, reg, [('out_file', 'moving_image')]),
        (reg, fslseg, [('warped_image', 'in_files')]),
        (fslseg, gmextract, [('partial_volume_files', 'pve_files')]),
        (gmextract, smooth, [('gm_file', 'in_files')]),
        (smooth, msk, [('smoothed_files', 'in_file')]),
        #(info_src, sinker, [('key', 'container')]),
        (bet, sinker, [('out_file', '@out_file')]),
        (reg, sinker, [('warped_image', '@warped_image')]),
        (fslseg, sinker, [('partial_volume_files', '@partial_volume_files')]),
        (msk, sinker, [('out_file', '@masked_smoothed_file')]),
    ])

    wf.run(plugin='MultiProc', plugin_args={'n_procs': 16})