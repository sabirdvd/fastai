from .imports import *
from .layer_optimizer import *
import copy


class Callback:
    def on_train_begin(self): pass
    def on_batch_begin(self): pass
    def on_epoch_end(self, metrics): pass
    def on_batch_end(self, metrics): pass
    def on_train_end(self): pass

# Useful for maintaining status of a long-running job.
# 
# Usage:
# learn.fit(0.01, 1, callbacks = [LoggingCallback(save_path="/tmp/log")])
class LoggingCallback(Callback):
    def __init__(self, save_path):
        super().__init__()
        self.save_path=save_path
    def on_train_begin(self):
        self.batch = 0
        self.epoch = 0
        self.f = open(self.save_path, "a", 1)
        self.log("\ton_train_begin")
    def on_batch_begin(self):
        self.log(str(self.batch)+"\ton_batch_begin")
    def on_epoch_end(self, metrics):
        self.log(str(self.epoch)+"\ton_epoch_end: "+str(metrics))
        self.epoch += 1
    def on_batch_end(self, metrics):
        self.log(str(self.batch)+"\ton_batch_end: "+str(metrics))
        self.batch += 1
    def on_train_end(self):
        self.log("\ton_train_end")
        self.f.close()
    def log(self, string):
        self.f.write(time.strftime("%Y-%m-%dT%H:%M:%S")+"\t"+string+"\n")

class LossRecorder(Callback):
    def __init__(self, layer_opt, save_path='', record_mom=False, metrics=[]):
        super().__init__()
        self.layer_opt=layer_opt
        self.init_lrs=np.array(layer_opt.lrs)
        self.save_path, self.record_mom, self.metrics = save_path, record_mom, metrics

    def on_train_begin(self):
        self.losses,self.lrs,self.iterations = [],[],[]
        self.val_losses, self.rec_metrics = [], []
        if self.record_mom:
            self.momentums = []
        self.iteration = 0
        self.epoch = 0

    def on_epoch_end(self, metrics):
        self.epoch += 1

    def on_batch_end(self, loss):
        self.iteration += 1
        self.lrs.append(self.layer_opt.lr)
        self.iterations.append(self.iteration)
        if isinstance(loss, list):
            self.losses.append(loss[0])
            self.save_metrics(loss[1:])
        else: self.losses.append(loss)
        if self.record_mom: self.momentums.append(self.layer_opt.mom)

    def save_metrics(self,vals):
        self.val_losses.append(vals[0])
        if len(vals) > 2: self.rec_metrics.append(vals[1:])
        elif len(vals) == 2: self.rec_metrics.append(vals[1])

    def plot_loss(self, n_skip=10, n_skip_end=5):
        if not in_ipynb(): plt.switch_backend('agg')
        plt.plot(self.iterations[n_skip:-n_skip_end], self.losses[n_skip:-n_skip_end])
        if not in_ipynb():
            plt.savefig(os.path.join(self.save_path, 'loss_plot.png'))
            np.save(os.path.join(self.save_path, 'losses.npy'), self.losses[10:])

    def plot_lr(self):
        if not in_ipynb():
            plt.switch_backend('agg')
        if self.record_mom:
            fig, axs = plt.subplots(1,2,figsize=(12,4))
            for i in range(0,2): axs[i].set_xlabel('iterations')
            axs[0].set_ylabel('learning rate')
            axs[1].set_ylabel('momentum')
            axs[0].plot(self.iterations,self.lrs)
            axs[1].plot(self.iterations,self.momentums)   
        else:
            plt.xlabel("iterations")
            plt.ylabel("learning rate")
            plt.plot(self.iterations, self.lrs)
        if not in_ipynb():
            plt.savefig(os.path.join(self.save_path, 'lr_plot.png'))


class LR_Updater(LossRecorder):
    def on_train_begin(self):
        super().on_train_begin()
        self.update_lr()
        if self.record_mom:
            self.update_mom()

    def on_batch_end(self, loss):
        res = super().on_batch_end(loss)
        self.update_lr()
        if self.record_mom:
            self.update_mom()
        return res

    def update_lr(self):
        new_lrs = self.calc_lr(self.init_lrs)
        self.layer_opt.set_lrs(new_lrs)
    
    def update_mom(self):
        new_mom = self.calc_mom()
        self.layer_opt.set_mom(new_mom)

    @abstractmethod
    def calc_lr(self, init_lrs): raise NotImplementedError
    
    @abstractmethod
    def calc_mom(self): raise NotImplementedError


class LR_Finder(LR_Updater):
    def __init__(self, layer_opt, nb, end_lr=10, linear=False, metrics = []):
        self.linear, self.stop_dv = linear, True
        ratio = end_lr/layer_opt.lr
        self.lr_mult = (ratio/nb) if linear else ratio**(1/nb)
        super().__init__(layer_opt,metrics=metrics)

    def on_train_begin(self):
        super().on_train_begin()
        self.best=1e9

    def calc_lr(self, init_lrs):
        mult = self.lr_mult*self.iteration if self.linear else self.lr_mult**self.iteration
        return init_lrs * mult

    def on_batch_end(self, metrics):
        loss = metrics[0] if isinstance(metrics,list) else metrics
        if self.stop_dv and (math.isnan(loss) or loss>self.best*4):
            return True
        if (loss<self.best and self.iteration>10): self.best=loss
        return super().on_batch_end(metrics)

    def plot(self, n_skip=10, n_skip_end=5):
        plt.ylabel("loss")
        plt.xlabel("learning rate (log scale)")
        plt.plot(self.lrs[n_skip:-n_skip_end], self.losses[n_skip:-n_skip_end])
        plt.xscale('log')

class LR_Finder2(LR_Finder):
    def __init__(self, layer_opt, nb, end_lr=10, linear=False, metrics=[], stop_dv=True):
        self.nb, self.metrics = nb, metrics
        super().__init__(layer_opt, nb, end_lr, linear, metrics)
        self.stop_dv = stop_dv

    def on_batch_end(self, loss):
        if self.iteration == self.nb:
            return True
        return super().on_batch_end(loss)

    def plot(self, n_skip=10, n_skip_end=5, smoothed=True):
        if self.metrics is None: self.metrics = []
        n_plots = len(self.metrics)+2
        fig, axs = plt.subplots(n_plots,figsize=(6,4*n_plots))
        for i in range(0,n_plots): axs[i].set_xlabel('learning rate')
        axs[0].set_ylabel('training loss')
        axs[1].set_ylabel('validation loss')
        for i,m in enumerate(self.metrics): 
            axs[i+2].set_ylabel(m.__name__)
            if len(self.metrics) == 1:
                values = self.rec_metrics
            else:
                values = [rec[i] for rec in self.rec_metrics]
            if smoothed: values = smooth_curve(values,0.98)
            axs[i+2].plot(self.lrs[n_skip:-n_skip_end], values[n_skip:-n_skip_end])
        plt_val_l = smooth_curve(self.val_losses, 0.98) if smoothed else self.val_losses
        axs[0].plot(self.lrs[n_skip:-n_skip_end],self.losses[n_skip:-n_skip_end])
        axs[1].plot(self.lrs[n_skip:-n_skip_end],plt_val_l[n_skip:-n_skip_end])

class CosAnneal(LR_Updater):
    def __init__(self, layer_opt, nb, on_cycle_end=None, cycle_mult=1):
        self.nb,self.on_cycle_end,self.cycle_mult = nb,on_cycle_end,cycle_mult
        super().__init__(layer_opt)

    def on_train_begin(self):
        self.cycle_iter,self.cycle_count=0,0
        super().on_train_begin()

    def calc_lr(self, init_lrs):
        if self.iteration<self.nb/20:
            self.cycle_iter += 1
            return init_lrs/100.

        cos_out = np.cos(np.pi*(self.cycle_iter)/self.nb) + 1
        self.cycle_iter += 1
        if self.cycle_iter==self.nb:
            self.cycle_iter = 0
            self.nb *= self.cycle_mult
            if self.on_cycle_end: self.on_cycle_end(self, self.cycle_count)
            self.cycle_count += 1
        return init_lrs / 2 * cos_out


class CircularLR(LR_Updater):
    def __init__(self, layer_opt, nb, div=4, cut_div=8, on_cycle_end=None, momentums=None):
        self.nb,self.div,self.cut_div,self.on_cycle_end = nb,div,cut_div,on_cycle_end
        if momentums is not None:
            self.moms = momentums
        super().__init__(layer_opt, record_mom=(momentums is not None))

    def on_train_begin(self):
        self.cycle_iter,self.cycle_count=0,0
        super().on_train_begin()

    def calc_lr(self, init_lrs):
        cut_pt = self.nb//self.cut_div
        if self.cycle_iter>cut_pt:
            pct = 1 - (self.cycle_iter - cut_pt)/(self.nb - cut_pt)
        else: pct = self.cycle_iter/cut_pt
        res = init_lrs * (1 + pct*(self.div-1)) / self.div
        self.cycle_iter += 1
        if self.cycle_iter==self.nb:
            self.cycle_iter = 0
            if self.on_cycle_end: self.on_cycle_end(self, self.cycle_count)
            self.cycle_count += 1
        return res
    
    def calc_mom(self):
        cut_pt = self.nb//self.cut_div
        if self.cycle_iter>cut_pt:
            pct = (self.cycle_iter - cut_pt)/(self.nb - cut_pt)
        else: pct = 1 - self.cycle_iter/cut_pt
        res = self.moms[1] + pct * (self.moms[0] - self.moms[1])
        return res

class CircularLR_beta(LR_Updater):
    def __init__(self, layer_opt, nb, div=10, pct=10, on_cycle_end=None, momentums=None):
        self.nb,self.div,self.pct,self.on_cycle_end = nb,div,pct,on_cycle_end
        self.cycle_nb = int(nb * (1-pct/100) / 2)
        if momentums is not None:
            self.moms = momentums
        super().__init__(layer_opt, record_mom=(momentums is not None))

    def on_train_begin(self):
        self.cycle_iter,self.cycle_count=0,0
        super().on_train_begin()

    def calc_lr(self, init_lrs):
        if self.cycle_iter>2 * self.cycle_nb:
            pct = (self.cycle_iter - 2*self.cycle_nb)/(self.nb - 2*self.cycle_nb)
            res = init_lrs * (1 + (pct * (1-100)/100)) / self.div 
        elif self.cycle_iter>self.cycle_nb:
            pct = 1 - (self.cycle_iter - self.cycle_nb)/self.cycle_nb
            res = init_lrs * (1 + pct*(self.div-1)) / self.div
        else: 
            pct = self.cycle_iter/self.cycle_nb
            res = init_lrs * (1 + pct*(self.div-1)) / self.div
        self.cycle_iter += 1
        if self.cycle_iter==self.nb:
            self.cycle_iter = 0
            if self.on_cycle_end: self.on_cycle_end(self, self.cycle_count)
            self.cycle_count += 1
        return res
    
    def calc_mom(self):
        if self.cycle_iter>2*self.cycle_nb:
            res = self.moms[0]
        elif self.cycle_iter>self.cycle_nb:
            pct = 1 - (self.cycle_iter - self.cycle_nb)/self.cycle_nb
            res = self.moms[0] + pct * (self.moms[1] - self.moms[0])
        else: 
            pct = self.cycle_iter/self.cycle_nb
            res = self.moms[0] + pct * (self.moms[1] - self.moms[0])
        return res


class SaveBestModel(LossRecorder):
    
    """ Save weights of the best model based during training.
        If metrics are provided, the first metric in the list is used to
        find the best model. 
        If no metrics are provided, the loss is used.
        
        Args:
            model: the fastai model
            lr: indicate to use test images; otherwise use validation images
            name: the name of filename of the weights without '.h5'
        
        Usage:
            Briefly, you have your model 'learn' variable and call fit.
            >>> learn.fit(lr, 2, cycle_len=2, cycle_mult=1, best_save_name='mybestmodel')
            ....
            >>> learn.load('mybestmodel')
            
            For more details see http://forums.fast.ai/t/a-code-snippet-to-save-the-best-model-during-training/12066
 
    """
    def __init__(self, model, layer_opt, metrics, name='best_model'):
        super().__init__(layer_opt)
        self.name = name
        self.model = model
        self.best_loss = None
        self.best_acc = None
        self.save_method = self.save_when_only_loss if metrics==None else self.save_when_acc
        
    def save_when_only_loss(self, metrics):
        loss = metrics[0]
        if self.best_loss == None or loss < self.best_loss:
            self.best_loss = loss
            self.model.save(f'{self.name}')
    
    def save_when_acc(self, metrics):
        loss, acc = metrics[0], metrics[1]
        if self.best_acc == None or acc > self.best_acc:
            self.best_acc = acc
            self.best_loss = loss
            self.model.save(f'{self.name}')
        elif acc == self.best_acc and  loss < self.best_loss:
            self.best_loss = loss
            self.model.save(f'{self.name}')
        
    def on_epoch_end(self, metrics):
        super().on_epoch_end(metrics)
        self.save_method(metrics)


class WeightDecaySchedule(Callback):
    def __init__(self, layer_opt, batch_per_epoch, cycle_len, cycle_mult, n_cycles, norm_wds=False, wds_sched_mult=None):
        """
        Implements the weight decay schedule as mentioned in https://arxiv.org/abs/1711.05101

        :param layer_opt: The LayerOptimizer
        :param batch_per_epoch: Num batches in 1 epoch
        :param cycle_len: Num epochs in initial cycle. Subsequent cycle_len = previous cycle_len * cycle_mult
        :param cycle_mult: Cycle multiplier
        :param n_cycles: Number of cycles to be executed
        """
        super().__init__()

        self.layer_opt = layer_opt
        self.batch_per_epoch = batch_per_epoch
        self.init_wds = np.array(layer_opt.wds)  # Weights as set by user
        self.init_lrs = np.array(layer_opt.lrs)  # Learning rates as set by user
        self.new_wds = None                      # Holds the new weight decay factors, calculated in on_batch_begin()
        self.param_groups_old = None             # Caches the old parameter values in on_batch_begin()
        self.iteration = 0
        self.epoch = 0
        self.wds_sched_mult = wds_sched_mult
        self.norm_wds = norm_wds
        self.wds_history = list()

        # Pre calculating the number of epochs in the cycle of current running epoch
        self.epoch_to_num_cycles, i = dict(), 0
        for cycle in range(n_cycles):
            for _ in range(cycle_len):
                self.epoch_to_num_cycles[i] = cycle_len
                i += 1
            cycle_len *= cycle_mult

    def on_train_begin(self):
        self.iteration = 0
        self.epoch = 0

    def on_batch_begin(self):
        # Prepare for decay of weights

        # Default weight decay (as provided by user)
        wdn = self.init_wds

        # Weight decay multiplier (The 'eta' in the paper). Optional.
        wdm = 1.0
        if self.wds_sched_mult is not None:
            wdm = self.wds_sched_mult(self)

        # Weight decay normalized. Optional.
        if self.norm_wds:
            wdn = wdn / np.sqrt(self.batch_per_epoch * self.epoch_to_num_cycles[self.epoch])

        # Final wds
        self.new_wds = wdm * wdn

        # Record the wds
        self.wds_history.append(self.new_wds)

        # Set weight_decay with zeros so that it is not applied in Adam, we will apply it outside in on_batch_end()
        self.layer_opt.set_wds(torch.zeros(self.new_wds.size))
        # We have to save the existing weights before the optimizer changes the values
        self.param_groups_old = copy.deepcopy(self.layer_opt.opt.param_groups)
        self.iteration += 1

    def on_batch_end(self, loss):
        # Decay the weights
        for group, group_old, wds in zip(self.layer_opt.opt.param_groups, self.param_groups_old, self.new_wds):
            for p, p_old in zip(group['params'], group_old['params']):
                if p.grad is None:
                    continue
                p.data = p.data.add(-wds, p_old.data)

    def on_epoch_end(self, metrics):
        self.epoch += 1

def smooth_curve(vals, beta):
    avg_val = 0
    smoothed = []
    for (i,v) in enumerate(vals):
        avg_val = beta * avg_val + (1-beta) * v
        smoothed.append(avg_val/(1-beta**(i+1)))
    return smoothed